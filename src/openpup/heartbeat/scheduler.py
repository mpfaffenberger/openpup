"""Lightweight routine scheduler (no cron dependency).

Routines are stored as JSON in the OpenPup state dir. Each routine has a
trigger that is either an interval (``every`` N seconds) or a daily wall-clock
time (``daily`` HH:MM). ``due()`` returns routines whose time has come and
records the fire time so they don't re-fire within the same window.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("openpup.scheduler")


@dataclass
class Routine:
    name: str
    prompt: str
    deliver: str  # "platform:channel" address
    # exactly one of these is used:
    every: Optional[int] = None  # seconds between runs
    daily: Optional[str] = None  # "HH:MM" local time
    last_run: float = 0.0
    enabled: bool = True

    def is_due(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.every:
            return (now - self.last_run) >= self.every
        if self.daily:
            try:
                hh, mm = (int(x) for x in self.daily.split(":"))
            except ValueError:
                return False
            local = datetime.fromtimestamp(now)
            if local.hour == hh and local.minute == mm:
                # only once per minute window
                return (now - self.last_run) > 90
        return False


@dataclass
class Scheduler:
    path: Path
    routines: List[Routine] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Scheduler":
        sched = cls(path=path)
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                sched.routines = [Routine(**r) for r in raw]
            except Exception:
                logger.exception("Failed to load routines from %s", path)
        return sched

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps([asdict(r) for r in self.routines], indent=2))
        except Exception:
            logger.exception("Failed to save routines")

    def add(self, routine: Routine) -> None:
        self.routines = [r for r in self.routines if r.name != routine.name]
        self.routines.append(routine)
        self.save()

    def remove(self, name: str) -> bool:
        before = len(self.routines)
        self.routines = [r for r in self.routines if r.name != name]
        self.save()
        return len(self.routines) < before

    def due(self, now: Optional[float] = None) -> List[Routine]:
        now = now if now is not None else time.time()
        fired = [r for r in self.routines if r.is_due(now)]
        for r in fired:
            r.last_run = now
        if fired:
            self.save()
        return fired
