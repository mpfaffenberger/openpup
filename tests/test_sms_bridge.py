"""Tests for the host-side ModemManager SMS bridge."""

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_BRIDGE_PATH = _REPO_ROOT / "sms_bridge.py"
_SPEC = importlib.util.spec_from_file_location("openpup_sms_bridge", _BRIDGE_PATH)
assert _SPEC and _SPEC.loader
sms_bridge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sms_bridge)


def test_send_sms_preserves_punctuation_via_text_file(monkeypatch) -> None:
    calls = []
    captured_text = []

    def fake_run_mmcli(*args, timeout=10):
        calls.append((args, timeout))
        text_arg = next(
            (arg for arg in args if arg.startswith("--messaging-create-sms-with-text=")),
            None,
        )
        if text_arg:
            captured_text.append(Path(text_arg.split("=", 1)[1]).read_text())
            return (
                "Messaging | created sms: "
                "/org/freedesktop/ModemManager1/SMS/42",
                "",
                0,
            )
        if "--send" in args:
            return "successfully sent the SMS", "", 0
        return "successfully deleted SMS from modem", "", 0

    monkeypatch.setattr(sms_bridge, "run_mmcli", fake_run_mmcli)
    text = 'Haiiii! I\'m here. "Mostly." What\'s up? \\o/'

    ok, result = sms_bridge.send_sms(
        "/org/freedesktop/ModemManager1/Modem/1",
        "+15551234567",
        text,
    )

    assert ok is True
    assert result == "successfully sent the SMS"
    assert captured_text == [text]
    create_args = calls[0][0]
    assert "--messaging-create-sms=number='+15551234567'" in create_args
    assert any(arg.startswith("--messaging-create-sms-with-text=") for arg in create_args)
    assert calls[1] == (("-s", "42", "--send"), 30)
    assert calls[2][0] == ("-m", "1", "--messaging-delete-sms", "42")


def test_send_sms_rejects_invalid_number_without_calling_mmcli(monkeypatch) -> None:
    fake_run = monkeypatch.setattr
    calls = []

    def record_call(*args, **kwargs):
        calls.append((args, kwargs))
        return "", "", 0

    fake_run(sms_bridge, "run_mmcli", record_call)

    ok, result = sms_bridge.send_sms(
        "/org/freedesktop/ModemManager1/Modem/1",
        "+1; rm -rf /",
        "nope",
    )

    assert ok is False
    assert result == "invalid destination number"
    assert calls == []
