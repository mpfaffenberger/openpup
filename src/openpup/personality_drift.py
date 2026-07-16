"""Personality drift: per-owner preference weights learned from ratings.

v1 keeps a small JSON store of weights per owner. The agent prompt is
augmented with a short summary of the weights so the LLM can adapt.

Settings:
  * ``OPENPUP_DRIFT_FILE`` -- path (default ``~/.openpup/drift.json``).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.personality_drift")


@dataclass
class DriftWeights:
    verbosity: float = 0.0  # -1 concise, +1 verbose
    formality: float = 0.0  # -1 casual, +1 formal
    emoji: float = 0.0  # -1 none, +1 more
    rated_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "DriftWeights":
        return cls(**raw)


def _file() -> Path:
    from openpup.config import config_home

    return Path(os.environ.get("OPENPUP_DRIFT_FILE", config_home() / "drift.json"))


def _load() -> dict[str, DriftWeights]:
    p = _file()
    if not p.exists():
        return {}
    try:
        return {k: DriftWeights.from_dict(v) for k, v in json.loads(p.read_text()).items()}
    except Exception:
        return {}


def _save(owners: dict[str, DriftWeights]) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: v.to_dict() for k, v in owners.items()}, indent=2))


def rate(owner: str, *, verbosity: float = 0, formality: float = 0, emoji: float = 0) -> DriftWeights:
    """Record a rating from the owner. v1 EMA over the weights."""
    owners = _load()
    w = owners.get(owner) or DriftWeights()
    a = 1.0 / (w.rated_count + 1) if w.rated_count >= 0 else 1.0
    w.verbosity = (1 - a) * w.verbosity + a * verbosity
    w.formality = (1 - a) * w.formality + a * formality
    w.emoji = (1 - a) * w.emoji + a * emoji
    w.rated_count += 1
    owners[owner] = w
    _save(owners)
    return w


def summary(owner: str) -> str:
    """Return a one-line summary of an owner's drift weights."""
    w = _load().get(owner)
    if not w:
        return ""
    parts = []
    if w.verbosity != 0:
        parts.append(f"verbosity={w.verbosity:+.1f}")
    if w.formality != 0:
        parts.append(f"formality={w.formality:+.1f}")
    if w.emoji != 0:
        parts.append(f"emoji={w.emoji:+.1f}")
    return "drift: " + ", ".join(parts)
