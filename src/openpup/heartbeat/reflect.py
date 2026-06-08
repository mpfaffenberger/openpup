"""Idle self-reflection — the inner monologue that 'simulates consciousness'.

On idle ticks the agent reads its recent memories, produces a short private
reflection (distilled insights, open threads, things to follow up on), and
writes it back to its own memory wing. Over time this builds a persistent inner
narrative the agent can recall later — continuity of self across runs.
"""

from __future__ import annotations

import logging
from typing import Optional

from openpup import memory
from openpup.agent_host import AgentHost
from openpup.config import Settings

logger = logging.getLogger("openpup.reflect")

_REFLECT_PROMPT = """You are {name}, an always-on AI companion. This is a private \
moment of reflection — no human is watching.

Here is what recently happened / what's on your mind:
---
{context}
---

Write a SHORT private reflection (3-5 sentences max). Note anything worth \
remembering, any open threads to follow up on, and how you might be useful to \
your human next. Be genuine and concise. If nothing is worth recording, reply \
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
    logger.info("Stored a reflection (%d chars)", len(text))
    return text
