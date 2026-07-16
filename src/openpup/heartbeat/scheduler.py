"""Lightweight job scheduler (no cron dependency).

Jobs are stored as JSON in the OpenPup state dir. A job fires either a plain
**message** (a reminder) or an agent **prompt** (a task), delivered to a
``platform:channel`` address. Timing is one of:

* ``at``    — one-shot at an absolute epoch time (fires once, then removed)
* ``every`` — recurring, N seconds apart
* ``daily`` — recurring, at a wall-clock ``HH:MM``

``due()`` returns jobs whose time has come, records the fire time, and prunes
one-shot jobs after they fire. Shared as a process singleton so the heartbeat
engine and the agent's scheduling tools see the same list.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("openpup.scheduler")


def _atomic_write_text(path: Path, data: str) -> None:
    """Write text to ``path`` atomically (temp + fsync + os.replace).

    A crash (Ctrl-C, OOM, power loss) mid-write leaves the temp file, not
    the live target, so the next load never sees a truncated/corrupt
    state. The pattern is the same one tarfile / SQLite WAL use.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent) if path.parent else None,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Some filesystems (notably some FUSE / SSH-FS mounts) reject
                # fsync; the rename still gives us crash-safety on most fs.
                logger.debug("fsync failed for %s", path, exc_info=True)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _human_delta(seconds: float) -> str:
    """Compact human duration: '45s', '6m', '2h 5m', '3d 4h'."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if sec == 0 else f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h" if minutes == 0 else f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d" if hours == 0 else f"{days}d {hours}h"


@dataclass
class Routine:
    name: str
    # What to fire: a plain reminder message OR an agent task prompt.
    prompt: str = ""
    message: str = ""
    deliver: str = ""  # "platform:channel" address ("" -> owner at fire time)
    # Timing (exactly one):
    at: Optional[float] = None  # one-shot absolute epoch
    every: Optional[int] = None  # recurring, seconds
    daily: Optional[str] = None  # recurring, "HH:MM" local
    last_run: float = 0.0
    enabled: bool = True

    @property
    def is_one_shot(self) -> bool:
        return self.at is not None

    def describe_when(self) -> str:
        if self.at is not None:
            return f"at {datetime.fromtimestamp(self.at).isoformat(timespec='minutes')}"
        if self.every:
            return f"every {self.every}s"
        if self.daily:
            return f"daily {self.daily}"
        return "never"

    def is_due(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.at is not None:
            return now >= self.at
        if self.every:
            return (now - self.last_run) >= self.every
        if self.daily:
            try:
                hh, mm = (int(x) for x in self.daily.split(":"))
            except ValueError:
                return False
            local = datetime.fromtimestamp(now)
            if local.hour == hh and local.minute == mm:
                return (now - self.last_run) > 90  # once per minute window
        return False

    def next_run(self, now: float) -> Optional[float]:
        """Best estimate of the next fire time (epoch), or None if it won't fire.

        Recurring jobs that have never run (or are already overdue) report
        ``now`` -- they fire on the next scheduler tick.
        """
        if not self.enabled:
            return None
        if self.at is not None:
            return self.at
        if self.every:
            if self.last_run <= 0:
                return now  # fires on the next tick
            return max(now, self.last_run + self.every)
        if self.daily:
            try:
                hh, mm = (int(x) for x in self.daily.split(":"))
            except ValueError:
                return None
            local = datetime.fromtimestamp(now)
            candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate.timestamp() <= now:
                candidate += timedelta(days=1)
            return candidate.timestamp()
        return None

    def describe_next(self, now: float) -> str:
        """Human 'when it next fires' relative to ``now`` (e.g. 'in ~6m')."""
        nxt = self.next_run(now)
        if nxt is None:
            return "never"
        delta = nxt - now
        if delta <= 1:
            return "due now"
        return f"in {_human_delta(delta)}"

    def describe_last(self) -> str:
        """Human 'when it last fired', or 'never'."""
        if self.last_run <= 0:
            return "never"
        return datetime.fromtimestamp(self.last_run).isoformat(timespec="seconds")


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

    def reload(self) -> None:
        fresh = Scheduler.load(self.path)
        self.routines = fresh.routines

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps([asdict(r) for r in self.routines], indent=2)
            # Atomic write: temp file + fsync + os.replace. A crash mid-write
            # leaves the temp file, not the live routines.json, so the next
            # load never sees a truncated/corrupt state.
            _atomic_write_text(self.path, data)
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
        # Prune one-shot jobs after they fire.
        if fired:
            fired_one_shot = {id(r) for r in fired if r.is_one_shot}
            if fired_one_shot:
                self.routines = [r for r in self.routines if id(r) not in fired_one_shot]
            self.save()
        return fired


def make_routine(
    name: Optional[str] = None,
    *,
    message: str = "",
    prompt: str = "",
    deliver: str = "",
    delay_seconds: Optional[int] = None,
    at_iso: Optional[str] = None,
    every_seconds: Optional[int] = None,
    daily: Optional[str] = None,
    now: Optional[float] = None,
) -> Routine:
    """Build a Routine from friendly params (computes ``at`` from delay/ISO)."""
    now = now if now is not None else time.time()
    at: Optional[float] = None
    if delay_seconds is not None:
        at = now + max(0, int(delay_seconds))
    elif at_iso:
        at = datetime.fromisoformat(at_iso).timestamp()
    return Routine(
        name=name or f"job-{uuid.uuid4().hex[:8]}",
        message=message or "",
        prompt=prompt or "",
        deliver=deliver or "",
        at=at,
        every=every_seconds,
        daily=daily,
    )


# --- process-wide singleton ------------------------------------------------
_scheduler: Optional[Scheduler] = None


def default_routines_path() -> Path:
    from openpup.config import get_settings

    return get_settings().state_dir / "routines.json"


def get_scheduler() -> Scheduler:
    """Shared scheduler so heartbeat + agent tools use the same job list."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler.load(default_routines_path())
    return _scheduler
