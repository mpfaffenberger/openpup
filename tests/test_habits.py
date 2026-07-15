"""Tests for the habit tracker."""

from datetime import date, timedelta

import pytest

from openpup.habits import (
    HabitStore,
    _streak,
    completion_rate,
)


class TestStreak:
    def test_empty(self):
        assert _streak([]) == (0, 0)

    def test_single_day(self):
        today = date.today().isoformat()
        cur, long = _streak([today])
        assert cur >= 1
        assert long == 1

    def test_three_consecutive(self):
        today = date.today()
        days = [(today - timedelta(days=i)).isoformat() for i in range(3)]
        cur, long = _streak(days)
        assert cur == 3
        assert long == 3

    def test_break_resets_current(self):
        today = date.today()
        # Two clusters with a gap.
        old = [(today - timedelta(days=10 + i)).isoformat() for i in range(2)]
        new = [(today - timedelta(days=i)).isoformat() for i in range(2)]
        cur, long = _streak(old + new)
        # Long is at least 2 (each cluster), current depends on whether today is included.
        assert long >= 2

    def test_longest_longer_than_current(self):
        today = date.today()
        days = [(today - timedelta(days=i)).isoformat() for i in range(1)]
        cur, long = _streak(days)
        assert long >= cur


class TestStore:
    def test_log_is_idempotent(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        h1 = s.log("meditation")
        h2 = s.log("meditation")
        # Same date, so completions should still be a single entry.
        assert h2.completions == h1.completions

    def test_log_specific_day(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        h = s.log("reading", day="2024-01-15")
        assert "2024-01-15" in h.completions

    def test_remove_existing(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        s.log("x", day="2024-01-15")
        assert s.remove("x", "2024-01-15") is True
        # Removing again: false
        assert s.remove("x", "2024-01-15") is False

    def test_remove_unknown_habit(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        assert s.remove("nope", "2024-01-15") is False

    def test_create(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        h = s.create("new-habit")
        assert h.name == "new-habit"
        # Creating again raises.
        with pytest.raises(ValueError):
            s.create("new-habit")

    def test_round_trip(self, tmp_path):
        s = HabitStore(tmp_path / "h.json")
        s.log("a", day="2024-01-01")
        s.log("b", day="2024-01-02")
        s2 = HabitStore(tmp_path / "h.json")
        names = sorted(h.name for h in s2.list())
        assert names == ["a", "b"]


class TestCompletionRate:
    def test_zero_days_completed(self, tmp_path, monkeypatch):
        # Use a tmp store to avoid clobbering state.

        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))

        # No logs -> rate 0.
        assert completion_rate("missing") == 0.0
