"""Tests for mmsd-tng D-Bus parsing and safe attachment extraction."""

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).parents[1] / "mms_bridge.py"
_SPEC = importlib.util.spec_from_file_location("openpup_mms_bridge", _MODULE_PATH)
assert _SPEC and _SPEC.loader
mms_bridge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mms_bridge)


def _payload(raw_path: Path, text_offset: int, image_offset: int, image: bytes) -> dict:
    properties = {
        "Status": {"type": "s", "data": "received"},
        "Sender": {"type": "s", "data": "+15551234567"},
        "Date": {"type": "s", "data": "2026-08-02T18:00:00-0400"},
        "Subject": {"type": "s", "data": "Pookle picture"},
        "Attachments": {
            "type": "a(ssstt)",
            "data": [
                ["text", "text/plain", str(raw_path), text_offset, 11],
                ["photo", "image/png", str(raw_path), image_offset, len(image)],
            ],
        },
    }
    return {
        "type": "a(oa{sv})",
        "data": [[[
            "/org/ofono/mms/modemmanager/message_123",
            properties,
        ]]],
    }


def test_poll_extracts_image_and_text_then_acknowledges(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    spool = tmp_path / "spool"
    storage.mkdir()
    text = b"hello puppy"
    image = b"\x89PNG\r\n\x1a\n" + b"image payload"
    prefix = b"MMS headers"
    raw = storage / "raw-pdu"
    raw.write_bytes(prefix + text + image)
    payload = _payload(raw, len(prefix), len(prefix) + len(text), image)
    deleted = []

    def delete_message(message_id: str) -> bool:
        deleted.append(message_id)
        return True

    inbox = mms_bridge.MMSInbox(
        storage,
        spool,
        "/data/mms-incoming",
        delete_message=delete_message,
    )

    messages = inbox.poll(payload)

    assert len(messages) == 1
    message = messages[0]
    assert message["id"] == "message_123"
    assert message["sender"] == "+15551234567"
    assert message["text"] == "Pookle picture\nhello puppy"
    assert message["attachments"] == [
        {
            "path": "/data/mms-incoming/message_123/image-02.png",
            "mime_type": "image/png",
            "size": len(image),
            "source": "mms",
        }
    ]
    extracted = spool / "message_123" / "image-02.png"
    assert extracted.read_bytes() == image
    assert inbox.acknowledge("message_123") is True
    assert deleted == ["message_123"]
    assert inbox.poll(payload) == []


def test_poll_rejects_attachment_outside_storage_root(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    spool = tmp_path / "spool"
    storage.mkdir()
    outside = tmp_path / "outside-pdu"
    image = b"\x89PNG\r\n\x1a\nunsafe"
    text = b"hello puppy"
    outside.write_bytes(text + image)
    payload = _payload(outside, 0, len(text), image)
    inbox = mms_bridge.MMSInbox(storage, spool)

    assert inbox.poll(payload) == []
    assert not list(spool.rglob("*.png"))


def test_poll_ignores_image_with_mismatched_magic(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    spool = tmp_path / "spool"
    storage.mkdir()
    text = b"hello puppy"
    fake_image = b"definitely not png"
    raw = storage / "raw-pdu"
    raw.write_bytes(text + fake_image)
    payload = _payload(raw, 0, len(text), fake_image)
    inbox = mms_bridge.MMSInbox(storage, spool)

    messages = inbox.poll(payload)

    assert len(messages) == 1
    assert messages[0]["attachments"] == []


def test_acknowledge_rejects_unsafe_identifier(tmp_path: Path) -> None:
    inbox = mms_bridge.MMSInbox(tmp_path / "storage", tmp_path / "spool")

    assert inbox.acknowledge("../../oops") is False
