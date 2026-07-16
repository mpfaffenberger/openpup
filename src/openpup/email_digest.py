"""Email digest batching: batch unread emails into a daily/hourly digest.

v1 is a stub: tracks last_digest_ts and a count, returns a synthetic
digest. Real email fetching + summarisation is a follow-up commit so v1
stays focused on the framework.

Settings:
  * ``OPENPUP_EMAIL_DIGEST_HOURS`` -- window in hours (default 24).
  * ``OPENPUP_DIGEST_FILE`` -- state file (default ``~/.openpup/digest.json``).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.email_digest")


@dataclass
class DigestState:
    last_digest_ts: float = 0.0
    delivered_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "DigestState":
        return cls(**raw)


def _file() -> Path:
    from openpup.config import config_home

    return Path(os.environ.get("OPENPUP_DIGEST_FILE", config_home() / "digest.json"))


def _load() -> DigestState:
    p = _file()
    if not p.exists():
        return DigestState()
    try:
        return DigestState.from_dict(json.loads(p.read_text()))
    except Exception:
        return DigestState()


def _save(state: DigestState) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state.to_dict(), indent=2))


def should_deliver(now: Optional[float] = None, *, window_hours: Optional[int] = None) -> bool:
    """True if enough time has elapsed since the last digest."""
    now = now if now is not None else time.time()
    win = window_hours if window_hours is not None else int(os.environ.get("OPENPUP_EMAIL_DIGEST_HOURS", "24"))
    state = _load()
    return (now - state.last_digest_ts) >= win * 3600


def deliver(emails: list[str], *, now: Optional[float] = None) -> dict:
    """Mark a digest as delivered. v1 returns a synthetic report.

    Args:
      emails: list of unread-email summaries.
    """
    now = now if now is not None else time.time()
    state = DigestState(last_digest_ts=now, delivered_count=len(emails))
    _save(state)
    return {"delivered": len(emails), "ts": int(now), "preview": emails[:3]}
