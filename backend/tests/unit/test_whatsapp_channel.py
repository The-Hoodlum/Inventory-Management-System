"""WhatsApp channel adapter: webhook verification, inbound parsing, send, and the
delegation flow into AssistantService (all with fakes — no DB, no network)."""
from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.assistant.whatsapp import MockWhatsAppAdapter
from app.integrations.whatsapp.service import WhatsAppChannelService
from app.integrations.whatsapp.utils import parse_inbound, verify_subscription

TENANT = str(uuid.uuid4())


def _text_payload(sender: str, body: str, msg_id: str = "wamid.1", ts: str = "1750000000") -> dict:
    return {"entry": [{"changes": [{"value": {"messaging_product": "whatsapp", "messages": [
        {"from": sender, "id": msg_id, "timestamp": ts, "type": "text", "text": {"body": body}}
    ]}}]}]}


# ------------------------------ verification ------------------------------- #
def test_verify_subscription_echoes_challenge_on_match():
    assert verify_subscription(mode="subscribe", token="T", challenge="42", verify_token="T") == "42"


def test_verify_subscription_rejects_bad_or_missing_token():
    assert verify_subscription(mode="subscribe", token="x", challenge="42", verify_token="T") is None
    assert verify_subscription(mode="subscribe", token="T", challenge="42", verify_token=None) is None
    assert verify_subscription(mode=None, token="T", challenge="42", verify_token="T") is None


# ------------------------------- parsing ----------------------------------- #
def test_parse_inbound_extracts_fields():
    msg = parse_inbound(_text_payload("+260999", "stock?", "wamid.9", "1750000123"))
    assert msg is not None
    assert msg.channel == "whatsapp"
    assert msg.sender == "+260999"
    assert msg.text == "stock?"
    assert msg.message_id == "wamid.9"
    assert msg.timestamp == dt.datetime.fromtimestamp(1750000123, tz=dt.UTC)


def test_parse_inbound_ignores_status_and_nontext_and_malformed():
    assert parse_inbound({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}) is None
    nontext = {"entry": [{"changes": [{"value": {"messages": [{"from": "x", "type": "image"}]}}]}]}
    assert parse_inbound(nontext) is None
    assert parse_inbound({}) is None
    assert parse_inbound({"entry": "oops"}) is None


# --------------------------- fakes for the service ------------------------- #
class _FakeSession:
    def __init__(self):
        self.guc = None

    async def execute(self, stmt, params=None):
        if params and "t" in params:
            self.guc = params["t"]
        return None


class _FakeAssistant:
    def __init__(self):
        self.calls = []

    async def whatsapp_reply(self, *, tenant_id, phone, text):
        self.calls.append((tenant_id, phone, text))
        return SimpleNamespace(reply="🏍️ 12 in Lusaka", ok=True, matched_user=True)


def _service(assistant, adapter, session, *, tenant_id=TENANT, verify_token="VT"):
    return WhatsAppChannelService(
        assistant=assistant, adapter=adapter, session=session,
        default_tenant_id=tenant_id, verify_token=verify_token,
    )


# ------------------------------- send -------------------------------------- #
async def test_send_text_message_uses_adapter():
    adapter = MockWhatsAppAdapter()
    svc = _service(_FakeAssistant(), adapter, _FakeSession())
    result = await svc.send_text_message("+260999", "hello")
    assert result.ok is True and result.to == "+260999"
    assert adapter.sent == [{"to": "+260999", "text": "hello"}]


# ----------------------------- inbound flow -------------------------------- #
async def test_handle_webhook_routes_to_assistant_and_replies():
    assistant, adapter, session = _FakeAssistant(), MockWhatsAppAdapter(), _FakeSession()
    svc = _service(assistant, adapter, session)
    ack = await svc.handle_webhook(_text_payload("+260999", "How many HLX 150 in Lusaka?"))
    assert ack.status == "processed"
    assert assistant.calls == [(uuid.UUID(TENANT), "+260999", "How many HLX 150 in Lusaka?")]
    assert session.guc == TENANT  # tenant GUC set for RLS
    assert adapter.sent[0]["to"] == "+260999" and "Lusaka" in adapter.sent[0]["text"]


async def test_handle_webhook_unrouted_without_default_tenant():
    assistant, adapter = _FakeAssistant(), MockWhatsAppAdapter()
    svc = _service(assistant, adapter, _FakeSession(), tenant_id=None)
    ack = await svc.handle_webhook(_text_payload("+260999", "hi"))
    assert ack.status == "received"
    assert assistant.calls == []      # not routed
    assert adapter.sent == []


async def test_handle_webhook_ignores_status_callbacks():
    assistant, adapter = _FakeAssistant(), MockWhatsAppAdapter()
    svc = _service(assistant, adapter, _FakeSession())
    ack = await svc.handle_webhook({"entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]})
    assert ack.status == "ignored"
    assert assistant.calls == []
