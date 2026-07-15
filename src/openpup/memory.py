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


#: Prefix the heartbeat stamps onto stored reflections (see reflect.py).
REFLECTION_PREFIX = "[reflection]"


def _is_reflection(text: str) -> bool:
    return text.lstrip().lower().startswith(REFLECTION_PREFIX)


def recent_memories(top_k: int = 8, include_reflections: bool = False) -> List[str]:
    """Recent kennel memories, by default EXCLUDING the pup's own reflections.

    The pup writes a reflection back into the kennel every heartbeat, so an
    unfiltered ``recent`` quickly fills up with the pup's own monologue. To
    ground reflection in what *actually happened* (conversations, contact
    notes, durable facts), we over-fetch and drop those reflection echoes,
    falling back to the raw recent set if there's nothing else around.
    """
    rows = recent(top_k=max(top_k * 3, top_k))
    if include_reflections:
        return rows[:top_k]
    grounded = [r for r in rows if not _is_reflection(r)]
    return (grounded or rows)[:top_k]


def recent_reflections(top_k: int = 3) -> List[str]:
    """The pup's most recent reflections only -- narrative continuity of self."""
    rows = recent(top_k=max(top_k * 8, top_k))
    return [r for r in rows if _is_reflection(r)][:top_k]


# --------------------------------------------------------------------------
# Per-contact memory: each unique person who messages OpenPup gets their own
# wing (``contact:<platform>:<channel>``), so the pup builds a memory profile
# of everyone it talks to.
# --------------------------------------------------------------------------
def contact_wing(address: str) -> str:
    return f"contact:{address}"


def remember_about_contact(
    address: str, content: str, name: str | None = None, room: str = "conversations"
) -> bool:
    """Record something in a specific person's memory wing."""
    if not address or not content or not content.strip():
        return False
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        meta = {"contact": address}
        if name:
            meta["name"] = name
        kennel.write_note(
            wing_name=contact_wing(address),
            room_name=room,
            content=content,
            role="note",
            metadata=meta,
        )
        return True
    except Exception:
        logger.debug("kennel remember_about_contact failed", exc_info=True)
        return False


def recall_about_contact(address: str, query: str, top_k: int = 3) -> List[str]:
    """Search a single person's memory wing."""
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        rows = kennel.search_drawers_multi(
            query=query, wing_names=[contact_wing(address)], limit=top_k
        )
        return [_row_text(r) for r in rows if _row_text(r)]
    except Exception:
        logger.debug("kennel recall_about_contact failed", exc_info=True)
        return []


def recent_about_contact(address: str, top_k: int = 3) -> List[str]:
    """Most recent notes in a single person's memory wing."""
    try:
        from code_puppy.plugins.puppy_kennel import kennel

        kennel.initialize()
        rows = kennel.recent_drawers(wing_name=contact_wing(address), limit=top_k)
        return [_row_text(r) for r in rows if _row_text(r)]
    except Exception:
        logger.debug("kennel recent_about_contact failed", exc_info=True)
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
