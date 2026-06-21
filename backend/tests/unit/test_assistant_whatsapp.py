"""WhatsApp adapter selection + Meta inbound normalization."""
from __future__ import annotations

from types import SimpleNamespace

from app.assistant.whatsapp import (
    CloudWhatsAppAdapter,
    MockWhatsAppAdapter,
    build_whatsapp_adapter,
    normalize_inbound,
)


def _meta_text_payload(sender: str, body: str) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": sender, "type": "text", "text": {"body": body}}
    ]}}]}]}


def test_normalize_valid_text_message():
    inbound = normalize_inbound(_meta_text_payload("+260999", "stock?"))
    assert inbound is not None
    assert inbound.from_ == "+260999"
    assert inbound.text == "stock?"


def test_normalize_ignores_status_callbacks_and_nontext():
    assert normalize_inbound({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}) is None
    image = {"entry": [{"changes": [{"value": {"messages": [{"from": "x", "type": "image"}]}}]}]}
    assert normalize_inbound(image) is None
    assert normalize_inbound({}) is None
    assert normalize_inbound({"entry": "bad"}) is None


async def test_mock_adapter_records_sends():
    a = MockWhatsAppAdapter()
    await a.send(to="+260111", text="hi")
    assert a.sent == [{"to": "+260111", "text": "hi"}]


def test_factory_selects_mock_by_default():
    s = SimpleNamespace(whatsapp_provider="mock", whatsapp_cloud_configured=False)
    assert isinstance(build_whatsapp_adapter(s), MockWhatsAppAdapter)


def test_factory_selects_cloud_when_configured():
    s = SimpleNamespace(
        whatsapp_provider="cloud", whatsapp_cloud_configured=True,
        whatsapp_phone_number_id="123", whatsapp_access_token="tok",
        whatsapp_api_base_url="https://graph.facebook.com/v21.0",
    )
    adapter = build_whatsapp_adapter(s)
    assert isinstance(adapter, CloudWhatsAppAdapter)
    assert "redacted" in repr(adapter)  # token never leaks


def test_factory_falls_back_to_mock_when_cloud_unconfigured():
    s = SimpleNamespace(whatsapp_provider="cloud", whatsapp_cloud_configured=False)
    assert isinstance(build_whatsapp_adapter(s), MockWhatsAppAdapter)
