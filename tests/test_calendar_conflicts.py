"""Tests for calendar conflict detection."""

from openpup.calendar_conflicts import CalendarEvent, find_conflicts, overlaps


def test_overlaps():
    a = CalendarEvent(start_ts=0, end_ts=60)
    b = CalendarEvent(start_ts=30, end_ts=90)
    assert overlaps(a, b)


def test_no_overlap():
    a = CalendarEvent(start_ts=0, end_ts=60)
    b = CalendarEvent(start_ts=60, end_ts=120)
    assert not overlaps(a, b)


def test_find_conflicts():
    existing = [
        CalendarEvent(start_ts=0, end_ts=60, title="standup"),
        CalendarEvent(start_ts=120, end_ts=180, title="lunch"),
    ]
    proposed = CalendarEvent(start_ts=30, end_ts=90, title="meeting")
    conflicts = find_conflicts(existing, proposed)
    assert len(conflicts) == 1
    assert conflicts[0].title == "standup"


def test_buffer():
    existing = [CalendarEvent(start_ts=60, end_ts=120, title="standup")]
    proposed = CalendarEvent(start_ts=0, end_ts=70, title="meeting")
    # No buffer: 0..70 conflicts with 60..120 -> conflict.
    assert len(find_conflicts(existing, proposed, buffer_min=0)) == 1
    # 15-min buffer: existing becomes 45..135; meeting 0..70 still
    # overlaps with that.
    assert len(find_conflicts(existing, proposed, buffer_min=15)) == 1
    # 100-min buffer: existing becomes -100..220; meeting 0..70 still
    # lies inside it -> still a conflict.
    assert len(find_conflicts(existing, proposed, buffer_min=100)) == 1
    # Proposed entirely before existing by >= buffer minutes: no
    # conflict at all (e.g. proposed is 0..0, existing at 60..120,
    # buffer=60 sec expands existing to 0..180; 0..0 doesn't overlap
    # 0..180 because b.end=0 <= a.start=0 -> no overlap).
    zero = CalendarEvent(start_ts=0, end_ts=0, title="before")
    assert len(find_conflicts(existing, zero, buffer_min=1)) == 0
