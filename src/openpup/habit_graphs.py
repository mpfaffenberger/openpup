"""Habit graphs: sparkline / calendar data for the dashboard tab.

This module extends ``habits.py`` with a ``recent(days)`` helper that
returns the last N days of completions, so the dashboard can render a
sparkline per habit.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from openpup.habits import Habit, HabitStore


@dataclass
class HabitDay:
    date: str  # YYYY-MM-DD
    done: bool


def recent(store: HabitStore, name: str, days: int = 30) -> list[HabitDay]:
    """Return the last N days for a habit (oldest first)."""
    habit = None
    for h in store.list():
        if h.name == name:
            habit = h
            break
    if not habit:
        return []
    today = time.time()
    out: list[HabitDay] = []
    for offset in range(days - 1, -1, -1):
        ts = today - offset * 86400
        d = time.strftime("%Y-%m-%d", time.gmtime(ts))
        out.append(HabitDay(date=d, done=d in habit.completions))
    return out


def sparkline_svg(days: list[HabitDay], *, width: int = 200, height: int = 30) -> str:
    """Render a tiny SVG sparkline from habit completion days."""
    if not days:
        return "<svg/>"
    n = len(days)
    bar_w = max(1, width // n)
    bar_h = height // 2
    bars = []
    for i, day in enumerate(days):
        x = i * bar_w
        y = 0 if day.done else bar_h
        fill = "#0a0" if day.done else "#ddd"
        bars.append(f'<rect x="{x}" y="{y}" width="{bar_w - 1}" height="{bar_h}" fill="{fill}"/>')
    return f'<svg width="{width}" height="{height}">' + "".join(bars) + "</svg>"
