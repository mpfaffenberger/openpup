"""Tests for personality drift."""

from openpup.personality_drift import rate, summary


def test_rate_creates_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_DRIFT_FILE", str(tmp_path / "d.json"))
    w = rate("alice", verbosity=1.0, formality=-1.0)
    assert w.rated_count == 1
    assert w.verbosity > 0
    assert w.formality < 0


def test_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_DRIFT_FILE", str(tmp_path / "d.json"))
    rate("bob", verbosity=0.5)
    s = summary("bob")
    assert "verbosity" in s


def test_summary_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_DRIFT_FILE", str(tmp_path / "d.json"))
    assert summary("nobody") == ""
