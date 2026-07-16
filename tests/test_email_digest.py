"""Tests for email digest."""

from openpup.email_digest import deliver, should_deliver


def test_should_deliver_after_window(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_DIGEST_FILE", str(tmp_path / "d.json"))
    # Initial: should deliver (no state).
    assert should_deliver(now=1700000000.0, window_hours=24) is True
    deliver(["a", "b", "c"], now=1700000000.0)
    # Just delivered -- no second digest within 24h.
    assert should_deliver(now=1700000001.0, window_hours=24) is False


def test_deliver(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_DIGEST_FILE", str(tmp_path / "d.json"))
    r = deliver(["hi"])
    assert r["delivered"] == 1
    assert "preview" in r
