"""Habit / streak tracker.

A lightweight JSON-backed store for daily habits (meditation, reading, exercise, ...).
Each habit has a name and a set of dates it was completed on. The store computes
current + longest streaks on demand.

CLI subcommand: ``openpup habits {list,log,check,streaks}``. Persisted to
``~/.openpup/habits.json`` (no daemon required).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.habits")

DEFAULT_STORE = "habits.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Habit:
    name: str
    completions: list[str] = field(default_factory=list)  # ISO dates (YYYY-MM-DD)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Habit":
        return cls(
            name=str(raw["name"]),
            completions=list(raw.get("completions", []) or []),
            created_at=float(raw.get("created_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Streak math
# ---------------------------------------------------------------------------
def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _streak(completions: list[str]) -> tuple[int, int]:
    """Return (current_streak, longest_streak) given a list of YYYY-MM-DD dates."""
    if not completions:
        return 0, 0
    days = sorted({_parse_date(s) for s in completions})
    longest = 1
    current = 1
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    # If the last day isn't today / yesterday, current streak might already be 0.
    today = date.today()
    if days and days[-1] < today - timedelta(days=1):
        current = 0
    return current, longest


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class HabitStore:
    """Persistent JSON-backed habit store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Habit]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            logger.exception("could not read habits file %s", self.path)
            return {}
        return {h["name"]: Habit.from_dict(h) for h in data.get("habits", [])}

    def _save(self, habits: dict[str, Habit]) -> None:
        data = {"habits": [h.to_dict() for h in habits.values()]}
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def list(self) -> list[Habit]:
        return sorted(self._load().values(), key=lambda h: h.name)

    def log(self, name: str, day: Optional[str] = None) -> Habit:
        """Mark the habit done on ``day`` (default today). Idempotent per day."""
        d = day or date.today().isoformat()
        habits = self._load()
        h = habits.get(name) or Habit(name=name)
        if d not in h.completions:
            h.completions.append(d)
            h.completions.sort()
        habits[name] = h
        self._save(habits)
        return h

    def remove(self, name: str, day: str) -> bool:
        """Remove one day from a habit. Returns True if anything was removed."""
        habits = self._load()
        if name not in habits:
            return False
        h = habits[name]
        if day in h.completions:
            h.completions.remove(day)
            self._save(habits)
            return True
        return False

    def create(self, name: str) -> Habit:
        habits = self._load()
        if name in habits:
            raise ValueError(f"habit {name!r} already exists")
        h = Habit(name=name)
        habits[name] = h
        self._save(habits)
        return h


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> HabitStore:
    return HabitStore(default_store_path())


def streaks_for(name: str) -> tuple[int, int]:
    """Return (current, longest) streak for a named habit."""
    for h in get_store().list():
        if h.name == name:
            return _streak(h.completions)
    return (0, 0)


def completion_rate(name: str, days: int = 30) -> float:
    """Fraction of days in the last ``days`` the habit was completed (0-1)."""
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=days - 1)
    completed = 0
    for h in get_store().list():
        if h.name != name:
            continue
        for s in h.completions:
            d = _parse_date(s)
            if start <= d <= end:
                completed += 1
        break
    return completed / max(days, 1)
