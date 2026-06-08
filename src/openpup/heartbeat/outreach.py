"""Proactive outreach — deciding whether to message the human unprompted.

Heavily guard-railed to avoid spam:
* respects quiet hours,
* hard daily cap (persisted to the state dir),
* the agent must explicitly opt in by starting its reply with ``REACH OUT:``;
  anything else is treated as "stay quiet".
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from openpup import memory
from openpup.agent_host import AgentHost
from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry

logger = logging.getLogger("openpup.outreach")

_OUTREACH_PROMPT = """You are {name}, an always-on AI companion. You may message \
your human ONLY if there is something genuinely worth their attention right now \
(a useful reminder, a finished background task, a timely thought).

Recent context / memory:
---
{context}
---

If — and only if — it is truly worth interrupting them, reply with:
REACH OUT: <the message to send>

Otherwise reply with exactly: STAY QUIET.
Bias strongly toward STAY QUIET. Do not invent reasons to reach out."""


def _counter_path(settings: Settings) -> Path:
    return settings.state_dir / "outreach_counter.json"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _remaining(settings: Settings) -> int:
    path = _counter_path(settings)
    try:
        data = json.loads(path.read_text())
        if data.get("date") == _today():
            return max(0, settings.outreach_max_per_day - int(data.get("count", 0)))
    except Exception:
        pass
    return settings.outreach_max_per_day


def _record_sent(settings: Settings) -> None:
    path = _counter_path(settings)
    count = 0
    try:
        data = json.loads(path.read_text())
        if data.get("date") == _today():
            count = int(data.get("count", 0))
    except Exception:
        pass
    path.write_text(json.dumps({"date": _today(), "count": count + 1}))


def _in_quiet_hours(settings: Settings, now: Optional[float] = None) -> bool:
    window = settings.quiet_window
    if not window:
        return False
    start, end = window
    hour = datetime.fromtimestamp(now or time.time()).hour
    if start <= end:
        return start <= hour < end
    # wraps midnight, e.g. 23-7
    return hour >= start or hour < end


async def maybe_reach_out(
    host: AgentHost, settings: Settings, registry: PlatformRegistry
) -> Optional[str]:
    """Decide and possibly send a proactive message. Returns sent text or None."""
    owner = settings.owner()
    if owner is None:
        logger.debug("No owner address configured; skipping outreach")
        return None
    if _in_quiet_hours(settings):
        logger.debug("In quiet hours; skipping outreach")
        return None
    if _remaining(settings) <= 0:
        logger.debug("Daily outreach cap reached; skipping")
        return None

    recent = memory.recent(top_k=6)
    context = "\n\n".join(recent) if recent else "Nothing notable."
    prompt = _OUTREACH_PROMPT.format(name=settings.name, context=context)

    try:
        decision = await host.run(
            prompt,
            conversation="__outreach__",
            model=settings.reflection_model,
            keep_history=False,
        )
    except Exception:
        logger.exception("Outreach decision run failed")
        return None

    decision = (decision or "").strip()
    if not decision.upper().startswith("REACH OUT:"):
        logger.debug("Agent chose to stay quiet")
        return None

    message = decision.split(":", 1)[1].strip()
    if not message:
        return None

    address = f"{owner[0]}:{owner[1]}"
    sent = await registry.send(Envelope.to(address, message))
    if sent:
        _record_sent(settings)
        memory.remember(
            f"[outreach -> {address}] {message}", wing=memory.AGENT_WING, room="outreach"
        )
        logger.info("Proactively reached out to %s", address)
        return message
    return None
