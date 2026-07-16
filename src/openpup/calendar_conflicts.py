"""Calendar conflict detection: warn before double-booking.

Wraps the existing ``calendar_integration`` API to compute overlap
between events. v1 is a thin detection layer; a real planner that
auto-suggests alternate slots is out of scope.

Settings: ``OPENPUP_CAL_CONFLICT_BUFFER_MIN`` (default 0) -- minutes of
buffer required between meetings to count as 'conflicting'.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("openpup.calendar_conflicts")


@dataclass
class CalendarEvent:
    """One event (existing or proposed)."""

    start_ts: int  # epoch seconds
    end_ts: int
    title: str = ""
    source: str = "existing"  # 'existing' | 'proposed'


def overlaps(a: CalendarEvent, b: CalendarEvent) -> bool:
    """Two events overlap when their intervals intersect."""
    return not (a.end_ts <= b.start_ts or b.end_ts <= a.start_ts)


def find_conflicts(
    events: list[CalendarEvent], proposed: CalendarEvent, *, buffer_min: int = 0
) -> list[CalendarEvent]:
    """Return all existing events that overlap with ``proposed``.

    ``buffer_min`` (minutes) expands each existing event to require a
    buffer between events.
    """
    buffer_s = buffer_min * 60
    out: list[CalendarEvent] = []
    for e in events:
        if e.source != "existing":
            continue
        # Expand e by buffer.
        expanded = CalendarEvent(
            start_ts=e.start_ts - buffer_s,
            end_ts=e.end_ts + buffer_s,
            title=e.title,
            source=e.source,
        )
        if overlaps(expanded, proposed):
            out.append(e)
    return out
