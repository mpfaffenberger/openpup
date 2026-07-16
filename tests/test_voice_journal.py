"""Tests for voice journal."""

from openpup.voice_journal import add, latest, list_recent


def test_add_creates_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_JOURNAL_FILE", str(tmp_path / "j.json"))
    e = add("today I shipped X")
    assert e.summary  # auto-generated


def test_latest_and_list(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_JOURNAL_FILE", str(tmp_path / "j.json"))
    add("first")
    add("second")
    e = latest()
    assert e is not None
    assert "second" in e.text
    items = list_recent()
    assert len(items) == 2
