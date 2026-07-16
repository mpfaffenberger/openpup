"""Tests for habit graphs."""

from openpup.habit_graphs import recent, sparkline_svg
from openpup.habits import HabitStore


def test_recent(tmp_path):
    s = HabitStore(tmp_path / "h.json")
    s.create("water")
    s.log("water")
    days = recent(s, "water", days=7)
    assert len(days) == 7
    assert days[-1].done is True


def test_recent_unknown_habit(tmp_path):
    s = HabitStore(tmp_path / "h.json")
    days = recent(s, "doesnotexist", days=7)
    assert days == []


def test_sparkline_svg_basic():
    from openpup.habit_graphs import HabitDay

    days = [HabitDay(date="2024-01-01", done=True)]
    svg = sparkline_svg(days)
    assert svg.startswith("<svg")
    assert "<rect" in svg
    assert svg.endswith("</svg>")


def test_sparkline_svg_empty():
    svg = sparkline_svg([])
    assert svg == "<svg/>"
