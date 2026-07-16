"""Voice journaling: dictate, summarise, persist.

v1 is a stub: each entry is stored verbatim with a synthetic summary.
Real STT (audio -> text) and real LLM summarisation are follow-up
commits so v1 stays focused on the framework.

Storage: ``~/.openpup/journal.json``.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.voice_journal")


@dataclass
class JournalEntry:
    ts: int
    text: str
    summary: str = ""
    audio_ref: str = ""  # path / url of original audio

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "JournalEntry":
        return cls(**raw)


def _file() -> Path:
    from openpup.config import config_home

    return Path(os.environ.get("OPENPUP_JOURNAL_FILE", config_home() / "journal.json"))


def _load() -> list[JournalEntry]:
    p = _file()
    if not p.exists():
        return []
    try:
        return [JournalEntry.from_dict(e) for e in json.loads(p.read_text()).get("entries", [])]
    except Exception:
        return []


def _save(entries: list[JournalEntry]) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entries": [e.to_dict() for e in entries]}, indent=2))


def add(text: str, *, audio_ref: str = "", summary: str = "") -> JournalEntry:
    """Add a journal entry. v1 summary is a synthetic truncation."""
    if not summary:
        # Synthetic summary: first 60 chars.
        summary = text.strip().replace("\n", " ")[:60] + ("..." if len(text) > 60 else "")
    e = JournalEntry(ts=int(time.time()), text=text, summary=summary, audio_ref=audio_ref or f"stub-{uuid.uuid4().hex[:8]}")
    entries = _load()
    entries.append(e)
    _save(entries)
    return e


def latest() -> Optional[JournalEntry]:
    entries = _load()
    return entries[-1] if entries else None


def list_recent(n: int = 10) -> list[JournalEntry]:
    return _load()[-n:]
