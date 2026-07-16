"""Tests for mood module."""

from openpup.mood import Mood, MoodStore


class TestMood:
    def test_invalid_score(self):
        import pytest

        with pytest.raises(ValueError):
            Mood(ts=1, score=10)

    def test_round_trip(self):
        m = Mood(ts=1, score=3, note="hi")
        d = m.to_dict()
        m2 = Mood.from_dict(d)
        assert m2.score == 3
        assert m2.note == "hi"


class TestStore:
    def test_log_and_recent(self, tmp_path):
        s = MoodStore(tmp_path / "m.json")
        s.log(3, note="ok")
        recent = s.recent()
        assert len(recent) == 1
        assert recent[0].score == 3

    def test_sparkline(self, tmp_path):
        s = MoodStore(tmp_path / "m.json")
        day = 1700000000 - (1700000000 % 86400)
        s.log(4, ts=day + 100)
        s.log(2, ts=day + 200)
        # Use a wide enough window to capture the historical timestamps.
        sparkline = s.sparkline(days=365 * 100)
        assert len(sparkline) >= 1
        # Find the day we just logged and check its average.
        match = next((entry for entry in sparkline if entry[0] == day), None)
        assert match is not None
        # avg of (4, 2) = 3
        assert match[1] == 3

    def test_invalid_score(self, tmp_path):
        import pytest

        s = MoodStore(tmp_path / "m.json")
        with pytest.raises(ValueError):
            s.log(0)
        with pytest.raises(ValueError):
            s.log(6)

    def test_sparkline(self, tmp_path):
        s = MoodStore(tmp_path / "m.json")
        day = 1700000000 - (1700000000 % 86400)
        s.log(4, ts=day + 100)
        s.log(2, ts=day + 200)
        # Use a wide enough window to capture the historical timestamps.
        sparkline = s.sparkline(days=365 * 100)
        assert len(sparkline) >= 1
        # Find the day we just logged and check its average.
        match = next((entry for entry in sparkline if entry[0] == day), None)
        assert match is not None
        # avg of (4, 2) = 3
        assert match[1] == 3
