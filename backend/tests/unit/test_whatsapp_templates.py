"""WhatsApp message templates — the path that lets SYSTEM-INITIATED messages survive
Meta's 24-hour customer-service window.

Two things carry real risk and are covered hardest here:
  1. Parameter sanitising. Meta rejects a parameter containing a newline, tab, or a blank
     value, which silently kills a whole alert over one missing field.
  2. The fallback. With no template configured the platform must behave EXACTLY as before,
     because templates need Meta's approval and cannot be a precondition for shipping.
"""
from __future__ import annotations

import pytest

from app.assistant.alerts import build_branch_daily_report_params
from app.assistant.whatsapp import (
    CloudWhatsAppAdapter,
    MockWhatsAppAdapter,
    deliver,
    template_param,
    template_params,
)


class TestTemplateParam:
    def test_flattens_newlines_and_tabs(self):
        # Meta rejects these outright, so a multi-line body must collapse to one line.
        assert template_param("Bike sold\nCustomer: Ann\tLusaka") == "Bike sold Customer: Ann Lusaka"

    def test_collapses_long_space_runs(self):
        # 4+ consecutive spaces are rejected too.
        assert template_param("Cash        5,000") == "Cash 5,000"

    @pytest.mark.parametrize("value", ["", "   ", None, "\n\t "])
    def test_blank_becomes_placeholder(self, value):
        # A customer with no address must not fail the entire send.
        assert template_param(value) == "-"

    def test_truncates_to_meta_limit(self):
        out = template_param("x" * 2000)
        assert len(out) == 1024 and out.endswith("…")

    def test_coerces_non_strings(self):
        assert template_params(7, 12.5, None) == ["7", "12.5", "-"]


class TestDeliver:
    @pytest.mark.asyncio
    async def test_without_template_sends_free_form(self):
        """The default: no template configured -> unchanged behaviour."""
        adapter = MockWhatsAppAdapter()
        await deliver(adapter, to="260977", text="Bike sold\nInvoice: INV-1")
        assert adapter.sent == [{"to": "260977", "text": "Bike sold\nInvoice: INV-1"}]

    @pytest.mark.asyncio
    async def test_with_template_sends_template_with_sanitised_params(self):
        adapter = MockWhatsAppAdapter()
        await deliver(
            adapter, to="260977", text="ignored free-form",
            template="bike_sold", params=("HLX 125\n(Red)", "", 4500),
        )
        sent = adapter.sent[0]
        assert sent["template"] == "bike_sold"
        assert sent["text"] == "HLX 125 (Red) | - | 4500"

    @pytest.mark.asyncio
    async def test_empty_template_name_is_treated_as_unset(self):
        """Blank is the shipped default for every template setting — it must not be
        mistaken for a real template name and sent to Meta."""
        adapter = MockWhatsAppAdapter()
        await deliver(adapter, to="260977", text="hello", template="", params=("a",))
        assert adapter.sent[0]["text"] == "hello" and "template" not in adapter.sent[0]


class TestCloudPayload:
    def _adapter(self):
        return CloudWhatsAppAdapter(
            phone_number_id="123", access_token="EAAsecret123",
            api_base_url="https://graph.facebook.com/v23.0",
        )

    @pytest.mark.asyncio
    async def test_builds_meta_template_payload(self, monkeypatch):
        captured = {}

        async def fake_post(payload, *, kind, template=""):
            captured.update(payload=payload, kind=kind)

        adapter = self._adapter()
        monkeypatch.setattr(adapter, "_post", fake_post)
        await adapter.send_template(
            to="260977", template="daily_summary", params=["Lusaka", "2026-07-20"], language="en",
        )
        payload = captured["payload"]
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "daily_summary"
        assert payload["template"]["language"] == {"code": "en"}
        # Positional order matters: params[0] fills {{1}}.
        assert payload["template"]["components"][0]["parameters"] == [
            {"type": "text", "text": "Lusaka"},
            {"type": "text", "text": "2026-07-20"},
        ]

    def test_repr_never_leaks_the_token(self):
        assert "EAAsecret123" not in repr(self._adapter())


class TestDailyDigestParams:
    def _digest(self, **over):
        base = {
            "branch": "Lusaka", "date": "2026-07-20",
            "sold": [{"description": "HLX 125", "qty": 2, "gross": 30000}],
            "payments": [{"method": "cash", "amount": 20000},
                         {"method": "mobile_money", "amount": 5000}],
            "gross_total": 30000, "collected_total": 25000, "outstanding_total": 5000,
            "order_requests": 2, "transfers": 1, "issuances": 0, "bike_issues": 0,
        }
        base.update(over)
        return base

    def test_five_params_in_template_order(self):
        p = build_branch_daily_report_params(self._digest(), currency="ZMW")
        assert len(p) == 5
        assert p[0] == "Lusaka" and p[1] == "2026-07-20"
        assert p[2] == "1 line(s) totalling ZMW 30,000.00"
        assert p[3] == "Cash ZMW 20,000.00, Mobile Money ZMW 5,000.00 (outstanding ZMW 5,000.00)"
        assert p[4] == "2 order request(s), 1 transfer(s)"

    def test_quiet_day_still_produces_non_blank_params(self):
        """Meta rejects blank parameters, so a day with no sales must not send empties."""
        p = build_branch_daily_report_params(
            self._digest(sold=[], payments=[], gross_total=0, collected_total=0,
                         outstanding_total=0, order_requests=0, transfers=0),
            currency="ZMW",
        )
        assert p[2] == "nothing today"
        assert p[3] == "ZMW 0.00 collected"
        assert p[4] == "no other activity"
        assert all(template_param(v) != "-" for v in p)

    def test_params_are_all_single_line(self):
        p = build_branch_daily_report_params(self._digest(), currency="ZMW")
        assert not any("\n" in v or "\t" in v for v in p)
