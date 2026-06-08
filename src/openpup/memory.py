"""Thin facade over code-puppy's puppy_kennel memory plugin.

The kennel (SQLite + FTS5, local-first) is already loaded as a code-puppy
plugin during ``AgentHost.boot()``. OpenPup uses it for two things beyond the
agent's own tool access:

* the heartbeat writes reflections / outreach decisions into the agent wing;
* OpenPup recalls recent context to decide whether proactive outreach is warranted.

All calls degrade gracefully to no-ops / empty results if the kennel is
unavailable, so OpenPup never crashes on a memory hiccup.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger("openpup.memory")

AGENT_WING = "agent"
USER_WING = "user"


def remember(content: str, wing: str = AGENT_WING, room: str = "notes") -> bool:
    """Write a verbatim note into the kennel. Returns success."""
    if not content or not content.strip():
        return False
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        kennel.write_note(wing_name=_wing_name(wing), room_name=room, content=content, role="note")
        return True
    except Exception:
        logger.debug("kennel remember failed", exc_info=True)
        return False


def recall(query: str, top_k: int = 5) -> List[str]:
    """BM25 search across wings; return matching drawer contents."""
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        rows = kennel.search_drawers_multi(query=query, limit=top_k)
        return [_row_text(r) for r in rows if _row_text(r)]
    except Exception:
        logger.debug("kennel recall failed", exc_info=True)
        return []


def recent(top_k: int = 5) -> List[str]:
    """Return the most recent drawers (no query needed)."""
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        rows = kennel.recent_drawers_multi(limit=top_k)
        return [_row_text(r) for r in rows if _row_text(r)]
    except Exception:
        logger.debug("kennel recent failed", exc_info=True)
        return []


def _wing_name(shortcut: str) -> str:
    """Map a wing shortcut to a concrete wing name the kennel understands."""
    if shortcut in (AGENT_WING, "agent"):
        return "agent:openpup"
    if shortcut in (USER_WING, "user"):
        return "user:default"
    return shortcut


def _row_text(row: object) -> str:
    """Best-effort extraction of text from a kennel row (dict or object)."""
    if isinstance(row, dict):
        return str(row.get("content") or row.get("text") or "").strip()
    return str(getattr(row, "content", "") or getattr(row, "text", "")).strip()
