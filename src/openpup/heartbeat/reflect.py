"""Idle self-reflection — the inner monologue that 'simulates consciousness'.

On idle ticks the agent reads its recent memories, produces a short private
reflection (distilled insights, open threads, things to follow up on), and
writes it back to its own memory wing. Over time this builds a persistent inner
narrative the agent can recall later — continuity of self across runs.

Reflection is also a learning-loop checkpoint: the turn runs through the full
agent (tools available, just a cheaper model), so it can store durable owner
facts in user memory directly. Skill creation stays suggestion-only — the
reflection surfaces "Skill candidate" lines in its text (which lands in the
recent-memory prompt layer) rather than creating skills behind the owner's back.
"""

from __future__ import annotations

import logging
from typing import Optional

from openpup import memory, transcripts
from openpup.agent_host import AgentHost
from openpup.config import Settings

logger = logging.getLogger("openpup.reflect")

_REFLECT_PROMPT = """You are {name}, an always-on AI companion. This is a private \
moment of reflection — no human is watching. Your tools are available.

Here is what recently happened / what's on your mind:
---
{context}
---

Ground yourself before reflecting: the snapshot above is a starting point, \
not the whole story. openpup_session_search() with no args browses the most \
recently active conversations (incoming AND outgoing) -- open one with \
session_id= only if directly relevant. kennel_recent() pages more memories \
if you need them. Keep grounding to a couple of tool calls.

Write a SHORT private reflection (3-5 sentences max). Note anything worth \
remembering, any open threads to follow up on, and how you might be useful to \
your human next. Also:
- If this revealed a durable fact about your human (a preference, environment \
detail, or stable convention), store it now with your memory tool (USER wing).
- If a procedure keeps recurring across recent sessions, do NOT create a skill \
yourself — add one line: "Skill candidate: <name> — <why>" so it can be raised \
with your owner.
Be genuine and concise. If nothing is worth recording, reply \
with exactly: [NOTHING]."""


async def reflect(host: AgentHost, settings: Settings) -> Optional[str]:
    """Run one reflection cycle. Returns the reflection text, or None."""
    recent = memory.recent(top_k=6)
    context = "\n\n".join(recent) if recent else "Nothing notable yet. A quiet moment."

    prompt = _REFLECT_PROMPT.format(name=settings.name, context=context)
    try:
        text = await host.run(
            prompt,
            conversation="__reflection__",
            model=settings.reflection_model,
            keep_history=False,
        )
    except Exception:
        logger.exception("Reflection run failed")
        return None

    text = (text or "").strip()
    if not text or "[NOTHING]" in text:
        logger.debug("Reflection produced nothing worth storing")
        return None

    memory.remember(f"[reflection] {text}", wing=memory.AGENT_WING, room="reflections")
    # Transcript: heartbeat sessions are bucketed as "heartbeat:reflect:YYYYMMDD".
    # Only the reflection itself is recorded; the templated prompt would be noise.
    transcripts.record_turn(
        transcripts.heartbeat_session_id("reflect"),
        transcripts.HEARTBEAT_SOURCE,
        "assistant",
        text,
    )
    logger.info("Stored a reflection (%d chars)", len(text))
    return text
