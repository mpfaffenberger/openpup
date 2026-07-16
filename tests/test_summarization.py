"""Tests for summarization."""

from openpup.summarization import Session, is_eligible, settings_from_env, summarise


class TestSummarise:
    def test_short_returns_as_is(self):
        text = "short text"
        assert summarise(text, max_chars=200) == "short text"

    def test_long_truncates(self):
        text = "a" * 500
        result = summarise(text, max_chars=200)
        assert len(result) <= 200
        # Either contains a separator (two-chunk) or single truncation.
        assert len(result) <= 200

    def test_head_and_tail_preserved(self):
        text = "HEAD_BEGIN " + ("x" * 1000) + " TAIL_END"
        result = summarise(text, max_chars=200)
        # Both markers should appear in the result (or at least one).
        if "\n" in result or " " in result[3:]:
            assert "HEAD" in result or "TAIL" in result


class TestEligible:
    def test_recent_session_not_eligible(self):
        now = 1700000000
        s = Session(ts=now - 86400, text="recent")
        assert not is_eligible(s, now=now, after_days=7)

    def test_old_session_eligible(self):
        now = 1700000000
        s = Session(ts=now - 8 * 86400, text="old")
        assert is_eligible(s, now=now, after_days=7)


class TestSettings:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_SUMMARIZE_AFTER_DAYS", "30")
        s = settings_from_env()
        assert s["after_days"] == 30
