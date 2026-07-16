"""Mood tracking: owner rates their mood (1-5) daily; the pup infers mood
from message tone; both surface as a graph in the dashboard.

The v1 scope is the explicit-rating dataclass + persist + sparkline math.
LLM inference (tone) and the dashboard tab are follow-up commits.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger("openpup.mood")

DEFAULT_STORE = "mood.json"
Source = Literal["explicit", "inferred"]


@dataclass
class Mood:
    ts: int
    score: int  # 1-5
    source: str = "explicit"  # 'explicit' or 'inferred'
    note: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.score <= 5:
            raise ValueError(f"score must be 1-5, got {self.score}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Mood":
        score = int(raw["score"])
        if not 1 <= score <= 5:
            raise ValueError(f"score must be 1-5, got {score}")
        return cls(
            ts=int(raw["ts"]),
            score=score,
            source=str(raw.get("source", "explicit")),
            note=str(raw.get("note", "")),
        )


class MoodStore:
    """JSON-backed store of mood entries."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[Mood]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            return []
        out: list[Mood] = []
        for m in raw.get("entries", []):
            try:
                out.append(Mood.from_dict(m))
            except Exception:
                continue
        return out

    def _save(self, entries: list[Mood]) -> None:
        out = {"entries": [m.to_dict() for m in entries]}
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def log(self, score: int, *, note: str = "", source: str = "explicit", ts: int | None = None) -> Mood:
        if not 1 <= score <= 5:
            raise ValueError("score must be 1-5")
        m = Mood(ts=ts or int(time.time()), score=score, source=source, note=note)
        entries = self._load()
        entries.append(m)
        entries.sort(key=lambda e: e.ts)
        self._save(entries)
        return m

    def recent(self, days: int = 30) -> list[Mood]:
        cutoff = int(time.time()) - days * 86400
        return [m for m in self._load() if m.ts >= cutoff]

    def sparkline(self, days: int = 30) -> list[tuple[int, int]]:
        """Return (day_epoch_start, avg_score) tuples for the last N days."""
        buckets: dict[int, list[int]] = {}
        for m in self.recent(days):
            day = m.ts - (m.ts % 86400)
            buckets.setdefault(day, []).append(m.score)
        out = []
        for day in sorted(buckets):
            scores = buckets[day]
            out.append((day, sum(scores) // len(scores)))
        return out


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> MoodStore:
    return MoodStore(default_store_path())
