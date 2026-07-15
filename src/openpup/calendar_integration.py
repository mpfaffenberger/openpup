"""Calendar integration for OpenPup.

v1 supports CalDAV servers (iCloud, Fastmail, Nextcloud, Radicale, etc.).
Google Calendar works via the same path because Google exposes a CalDAV
endpoint at ``https://apidata.googleusercontent.com/caldav/...`` -- but the
OAuth flow needs extra setup. For Google-specific setups, set
``OPENPUP_CALENDAR_PROVIDER=google`` and provide an OAuth token; otherwise
we fall through to CalDAV.

Tools exposed to the agent are wired via the existing ``openpup_calendar``
helper. CLI commands (``openpup calendar today|week|list|free``) give a quick
read-only view.

Configuration (env / config):

* ``OPENPUP_CALENDAR_URL`` -- CalDAV server URL (e.g. ``https://caldav.icloud.com``)
* ``OPENPUP_CALENDAR_USER`` -- username
* ``OPENPUP_CALENDAR_PASSWORD`` -- password / app-specific password
* ``OPENPUP_CALENDAR_DEFAULT`` -- default calendar name (else "default")
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("openpup.calendar")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    location: str = ""
    description: str = ""
    all_day: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "location": self.location,
            "description": self.description,
            "all_day": self.all_day,
        }


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------
class CalendarBackend:
    """Abstract base; subclasses implement ``list_events`` / ``create_event`` / etc."""

    def list_events(
        self, calendar: str, start: datetime, end: datetime, limit: int = 20
    ) -> list[CalendarEvent]:
        raise NotImplementedError

    def find_free_slot(
        self,
        calendar: str,
        duration_minutes: int,
        start: datetime,
        end: datetime,
    ) -> Optional[tuple[datetime, datetime]]:
        raise NotImplementedError

    def create_event(
        self,
        calendar: str,
        summary: str,
        start: datetime,
        end: datetime,
        location: str = "",
        description: str = "",
    ) -> CalendarEvent:
        raise NotImplementedError

    def reschedule(
        self, calendar: str, event_id: str, start: datetime, end: datetime
    ) -> CalendarEvent:
        raise NotImplementedError

    def cancel(self, calendar: str, event_id: str) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Stub backend (returns empty data; used when no provider is configured)
# ---------------------------------------------------------------------------
class StubBackend(CalendarBackend):
    """Returns empty results when no provider is configured.

    Lets the CLI run and report 'no calendar configured' rather than crashing.
    """

    def list_events(self, calendar, start, end, limit=20) -> list[CalendarEvent]:
        return []

    def find_free_slot(self, calendar, duration_minutes, start, end):
        return None

    def create_event(self, calendar, summary, start, end, location="", description=""):
        raise RuntimeError(
            "no calendar configured. Set OPENPUP_CALENDAR_URL/USER/PASSWORD or "
            "OPENPUP_GOOGLE_CALENDAR_CREDENTIALS to enable CalDAV / Google Calendar."
        )

    def reschedule(self, calendar, event_id, start, end):
        raise RuntimeError("no calendar configured")

    def cancel(self, calendar, event_id) -> bool:
        raise RuntimeError("no calendar configured")


# ---------------------------------------------------------------------------
# CalDAV backend
# ---------------------------------------------------------------------------
class CalDAVBackend(CalendarBackend):
    """Standard CalDAV backend (works for iCloud, Fastmail, Nextcloud, Radicale, ...)."""

    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.user = user
        self.password = password

    def _client(self):
        import caldav

        return caldav.DAVClient(url=self.url, username=self.user, password=self.password)

    def _principal(self):
        client = self._client()
        return client.principal()

    def _calendar(self, name: str):
        principal = self._principal()
        try:
            return principal.calendar(cal_id=name)
        except Exception:
            # Fall back to default calendar.
            return principal.calendar(cal_id="default")

    def _events(self, calendar: str, start: datetime, end: datetime):
        cal = self._calendar(calendar)
        try:
            events = cal.date_search(start=start, end=end)
        except Exception as exc:
            logger.warning("CalDAV date_search failed: %r", exc)
            return []
        return events or []

    def list_events(self, calendar, start, end, limit=20):
        out: list[CalendarEvent] = []
        for ev in self._events(calendar, start, end):
            vobj = getattr(ev, "vobject_instance", None) or getattr(ev, "icalendar_instance", None)
            if vobj is None:
                continue
            try:
                comp = vobj.vevent
                summary = str(comp.summary.value) if hasattr(comp, "summary") else "(no title)"
                dtstart = comp.dtstart.value
                dtend = comp.dtend.value if hasattr(comp, "dtend") else dtstart
                location = str(comp.location.value) if hasattr(comp, "location") else ""
                description = str(comp.description.value) if hasattr(comp, "description") else ""
            except Exception:
                continue
            # Normalise to timezone-aware datetimes.
            start_dt = _as_aware(dtstart)
            end_dt = _as_aware(dtend)
            out.append(
                CalendarEvent(
                    id=getattr(ev, "id", str(ev)),
                    summary=summary,
                    start=start_dt,
                    end=end_dt,
                    location=location,
                    description=description,
                    all_day=getattr(dtstart, "hour", None) is None,
                )
            )
            if len(out) >= limit:
                break
        return out

    def find_free_slot(self, calendar, duration_minutes, start, end):
        """Find the first free window of ``duration_minutes`` between start and end."""
        events = self.list_events(calendar, start, end, limit=200)
        cursor = start
        step = timedelta(minutes=15)
        duration = timedelta(minutes=duration_minutes)
        # Iterate until we find a window long enough.
        while cursor + duration <= end:
            # Advance past the current event (if any) to find the next gap.
            in_event = False
            for ev in events:
                if ev.start <= cursor < ev.end:
                    cursor = ev.end
                    in_event = True
                    break
            if in_event:
                continue
            # cursor is free; check the rest of the window.
            slot_end = cursor + duration
            if slot_end > end:
                return None
            for ev in events:
                if ev.start < slot_end <= ev.end or ev.start <= cursor < ev.end or (
                    cursor < ev.start < slot_end
                ):
                    # Conflict -- jump past this event.
                    cursor = ev.end
                    in_event = True
                    break
            if in_event:
                continue
            return (cursor, slot_end)
            cursor += step
        return None

    def create_event(self, calendar, summary, start, end, location="", description=""):
        from icalendar import Calendar as iCal, Event

        cal = self._calendar(calendar)
        ev = Event()
        ev.add("summary", summary)
        ev.add("dtstart", start)
        ev.add("dtend", end)
        if location:
            ev.add("location", location)
        if description:
            ev.add("description", description)
        result = cal.save_event(ical=ev)
        return CalendarEvent(
            id=str(result) if result else f"{calendar}:{start.isoformat()}",
            summary=summary,
            start=start,
            end=end,
            location=location,
            description=description,
        )

    def reschedule(self, calendar, event_id, start, end):
        cal = self._calendar(calendar)
        ev = cal.event_by_url(event_id) if event_id.startswith("http") else None
        if ev is None:
            # Search by id (UID).
            for e in self._events(calendar, start - timedelta(days=1), end + timedelta(days=1)):
                if e.id == event_id:
                    ev = e
                    break
        if ev is None:
            raise RuntimeError(f"event {event_id!r} not found")
        ev.vobject_instance.vevent.dtstart.value = start
        ev.vobject_instance.vevent.dtend.value = end
        ev.save()
        return CalendarEvent(id=event_id, summary="(updated)", start=start, end=end)

    def cancel(self, calendar, event_id) -> bool:
        try:
            cal = self._calendar(calendar)
            if event_id.startswith("http"):
                cal.event_by_url(event_id).delete()
            else:
                cal.event(event_id).delete()
            return True
        except Exception:
            return False


def _as_aware(dt) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    # date or date-time without tzinfo -> treat as UTC at midnight.
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Backend selector
# ---------------------------------------------------------------------------
def get_backend():
    """Return the configured backend, or a StubBackend if nothing is set."""
    url = os.environ.get("OPENPUP_CALENDAR_URL")
    user = os.environ.get("OPENPUP_CALENDAR_USER")
    password = os.environ.get("OPENPUP_CALENDAR_PASSWORD")
    if url and user and password:
        try:
            return CalDAVBackend(url, user, password)
        except Exception as exc:
            logger.warning("could not init CalDAV backend: %r", exc)
    return StubBackend()


def default_calendar() -> str:
    return os.environ.get("OPENPUP_CALENDAR_DEFAULT") or "default"
