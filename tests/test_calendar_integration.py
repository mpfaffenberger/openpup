"""Tests for the calendar integration module.

Covers the data model, the stub backend (no provider), and the backend
selector logic.
"""

import pytest

from openpup.calendar_integration import (
    CalendarEvent,
    StubBackend,
    default_calendar,
    get_backend,
)


class TestEventModel:
    def test_to_dict(self):
        from datetime import datetime, timezone

        e = CalendarEvent(
            id="x",
            summary="standup",
            start=datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc),
            end=datetime(2024, 6, 1, 9, 30, tzinfo=timezone.utc),
            location="Zoom",
        )
        d = e.to_dict()
        assert d["summary"] == "standup"
        assert d["location"] == "Zoom"
        assert d["start"].startswith("2024-06-01")


class TestStubBackend:
    def test_list_returns_empty(self):
        from datetime import datetime, timezone

        b = StubBackend()
        s = datetime(2024, 1, 1, tzinfo=timezone.utc)
        evts = b.list_events("default", s, s)
        assert evts == []

    def test_find_free_slot_returns_none(self):
        from datetime import datetime, timezone

        b = StubBackend()
        s = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = b.find_free_slot("default", 30, s, s)
        assert result is None

    def test_writes_fail_without_provider(self):
        from datetime import datetime, timezone

        b = StubBackend()
        s = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(RuntimeError, match="no calendar configured"):
            b.create_event("default", "x", s, s)
        with pytest.raises(RuntimeError):
            b.reschedule("default", "x", s, s)
        with pytest.raises(RuntimeError):
            b.cancel("default", "x")


class TestBackendSelector:
    def test_no_config_returns_stub(self, monkeypatch):
        for k in (
            "OPENPUP_CALENDAR_URL",
            "OPENPUP_CALENDAR_USER",
            "OPENPUP_CALENDAR_PASSWORD",
        ):
            monkeypatch.delenv(k, raising=False)
        assert isinstance(get_backend(), StubBackend)

    def test_default_calendar_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_CALENDAR_DEFAULT", "personal")
        assert default_calendar() == "personal"

    def test_default_calendar_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_CALENDAR_DEFAULT", raising=False)
        assert default_calendar() == "default"
