"""Auto-summarisation: roll long session transcripts into a short kennel note.

For v1 this is a deterministic text-truncation + lead-selection fallback.
A real LLM-based summary lands in a follow-up commit so v1 stays focused
on the rolling-window + opt-in logic.

Settings (env vars):
  * ``OPENPUP_SUMMARIZE_AFTER_DAYS`` (default 7): minimum session age to
    qualify for summary.
  * ``OPENPUP_SUMMARIZE_MAX_CHARS`` (default 200): max length of summary.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger("openpup.summarization")


@dataclass
class Session:
    ts: int
    text: str
    role: str = "user"  # user / assistant


def is_eligible(session: Session, *, now: int | None = None, after_days: int = 7) -> bool:
    """True if the session is old enough to be summarised."""
    now = now if now is not None else int(time.time())
    return (now - session.ts) >= after_days * 86400


def summarise(
    text: str, *, max_chars: int = 200, separator: str = "\n\n"
) -> str:
    """Roll long text into a short summary.

    v1 fallback: keep the first chunk + last chunk of equal length, joined
    with ``separator``. Truncates to ``max_chars``. v2 will replace this
    with an LLM-based summary when a real backend is wired in.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    half = max_chars // 2 - len(separator) // 2
    if half <= 0:
        return text[:max_chars]
    head = text[:half].rstrip()
    tail = text[-half:].lstrip()
    out = f"{head}{separator}{tail}"
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "\u2026"
    return out


def settings_from_env() -> dict[str, int]:
    return {
        "after_days": int(os.environ.get("OPENPUP_SUMMARIZE_AFTER_DAYS", "7") or 7),
        "max_chars": int(os.environ.get("OPENPUP_SUMMARIZE_MAX_CHARS", "200") or 200),
    }
