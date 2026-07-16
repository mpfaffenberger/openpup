"""Family accountability: track personal commitments with a due date.

Owner declares "I told my partner I'd take the trash out on Tuesday". The
pup pings on the day and tracks follow-through. Storage at
``~/.openpup/accountability.json``.

This is v1: text + due date + status. Recurring commitments and
multi-owner shared commitments are out of scope.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.accountability")

DEFAULT_STORE = "accountability.json"


@dataclass
class Commitment:
    text: str
    due_ts: int  # epoch seconds
    created_ts: int = field(default_factory=lambda: int(time.time()))
    done_ts: Optional[int] = None  # when follow-through completed
    abandoned_ts: Optional[int] = None  # when explicitly abandoned

    @property
    def status(self) -> str:
        if self.done_ts:
            return "done"
        if self.abandoned_ts:
            return "abandoned"
        return "pending"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Commitment":
        return cls(
            text=str(raw["text"]),
            due_ts=int(raw["due_ts"]),
            created_ts=int(raw.get("created_ts", time.time())),
            done_ts=raw.get("done_ts"),
            abandoned_ts=raw.get("abandoned_ts"),
        )


class CommitmentStore:
    """JSON-backed store of commitments."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Commitment]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            return {}
        out: dict[str, Commitment] = {}
        for c in raw.get("commitments", []):
            obj = Commitment.from_dict(c)
            out[f"{obj.created_ts}:{obj.text[:40]}"] = obj
        return out

    def _save(self, items: dict[str, Commitment]) -> None:
        out = {"commitments": [c.to_dict() for c in items.values()]}
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def add(self, text: str, due_ts: int) -> Commitment:
        c = Commitment(text=text, due_ts=due_ts)
        items = self._load()
        items[f"{c.created_ts}:{c.text[:40]}"] = c
        self._save(items)
        return c

    def list(self, status: str = "all") -> list[Commitment]:
        all_ = sorted(self._load().values(), key=lambda c: c.due_ts)
        if status == "all":
            return all_
        return [c for c in all_ if c.status == status]

    def due_today(self, today_ts: int) -> list[Commitment]:
        """Return commitments whose due_ts is within today (start..end)."""
        start = today_ts - (today_ts % 86400)
        end = start + 86400
        out = []
        for c in self.list("pending"):
            if start <= c.due_ts < end:
                out.append(c)
        return out

    def complete(self, key: str, when_ts: Optional[int] = None) -> bool:
        items = self._load()
        if key not in items:
            return False
        items[key].done_ts = when_ts or int(time.time())
        self._save(items)
        return True

    def abandon(self, key: str, when_ts: Optional[int] = None) -> bool:
        items = self._load()
        if key not in items:
            return False
        items[key].abandoned_ts = when_ts or int(time.time())
        self._save(items)
        return True


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> CommitmentStore:
    return CommitmentStore(default_store_path())
