"""Regression tests for direct-modem SMS message sizing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.modem_sms_adapter import (
    TRUNCATION_NOTICE,
    ModemSMSAdapter,
    _bounded_sms_text,
)


def test_text_within_limit_is_unchanged() -> None:
    text = "x" * 200

    assert _bounded_sms_text(text, 1500) == text


def test_text_over_limit_has_visible_truncation_notice() -> None:
    result = _bounded_sms_text("x" * 2000, 1500)

    assert len(result) == 1500
    assert result.endswith(TRUNCATION_NOTICE)


def test_tiny_limit_remains_bounded() -> None:
    assert _bounded_sms_text("abcdefgh", 5) == "abcde"


@pytest.mark.asyncio
async def test_send_passes_long_text_to_bridge_without_single_sms_truncation() -> None:
    settings = Settings(
        _env_file=None,
        SMS_ENABLED=True,
        SMS_BACKEND="modem",
        MODEM_BRIDGE_URL="http://bridge.test:9081",
        MODEM_SMS_MAX_CHARS=1500,
    )
    adapter = ModemSMSAdapter(settings, PlatformRegistry())
    await adapter._client.aclose()

    response = MagicMock()
    response.json.return_value = {"status": "sent"}
    adapter._client = MagicMock()
    adapter._client.post = AsyncMock(return_value=response)
    text = "Pookle has more than one SMS segment worth of opinions. " + ("x" * 180)

    await adapter.send(Envelope.to("sms:+15551234567", text))

    adapter._client.post.assert_awaited_once_with(
        "http://bridge.test:9081/sms/send",
        json={"number": "+15551234567", "text": text},
    )
    response.raise_for_status.assert_called_once_with()


@pytest.mark.asyncio
async def test_send_applies_configured_total_safety_cap() -> None:
    settings = Settings(
        _env_file=None,
        SMS_ENABLED=True,
        SMS_BACKEND="modem",
        MODEM_BRIDGE_URL="http://bridge.test:9081",
        MODEM_SMS_MAX_CHARS=160,
    )
    adapter = ModemSMSAdapter(settings, PlatformRegistry())
    await adapter._client.aclose()

    response = MagicMock()
    response.json.return_value = {"status": "sent"}
    adapter._client = MagicMock()
    adapter._client.post = AsyncMock(return_value=response)

    await adapter.send(Envelope.to("sms:+15551234567", "x" * 300))

    payload = adapter._client.post.await_args.kwargs["json"]
    assert len(payload["text"]) == 160
    assert payload["text"].endswith(TRUNCATION_NOTICE)


@pytest.mark.asyncio
async def test_mms_poll_dispatches_attachments_then_acknowledges() -> None:
    settings = Settings(
        _env_file=None,
        SMS_ENABLED=True,
        MMS_ENABLED=True,
        SMS_BACKEND="modem",
        MODEM_BRIDGE_URL="http://bridge.test:9081",
    )
    registry = PlatformRegistry()
    received = []

    async def collect(envelope: Envelope) -> None:
        received.append(envelope)

    registry.set_inbound_handler(collect)
    adapter = ModemSMSAdapter(settings, registry)
    await adapter._client.aclose()
    response = MagicMock()
    response.json.return_value = {
        "messages": [
            {
                "id": "mms-1",
                "sender": "+15551234567",
                "text": "look at this",
                "date": "2026-08-02T18:00:00-0400",
                "attachments": [
                    {
                        "path": "/data/mms-incoming/mms-1/image-01.jpg",
                        "mime_type": "image/jpeg",
                    }
                ],
            }
        ]
    }
    ack = MagicMock()
    adapter._client = MagicMock()
    adapter._client.get = AsyncMock(return_value=response)
    adapter._client.post = AsyncMock(return_value=ack)

    await adapter._check_new_mms()

    assert len(received) == 1
    assert received[0].attachments[0]["mime_type"] == "image/jpeg"
    adapter._client.post.assert_awaited_once_with(
        "http://bridge.test:9081/mms/ack",
        json={"id": "mms-1"},
    )
    response.raise_for_status.assert_called_once_with()
    ack.raise_for_status.assert_called_once_with()


def test_runtime_attachment_context_requires_image_tool() -> None:
    from openpup.runtime import OpenPup

    envelope = Envelope(
        platform="sms",
        channel="+15551234567",
        text="what is this?",
        attachments=[
            {
                "path": "/data/mms-incoming/mms-1/image-01.jpg",
                "mime_type": "image/jpeg",
            }
        ],
    )

    context = OpenPup._attachment_context(envelope)

    assert "load_image_for_analysis" in context
    assert "/data/mms-incoming/mms-1/image-01.jpg" in context
