"""Scheduled routines — cron-style agent tasks delivered to a platform.

On each heartbeat tick, due routines are run through the agent and their output
delivered to the routine's configured address (unless the agent emits the
``[SILENT]`` sentinel, mirroring hermes' no-spam pattern).
"""

from __future__ import annotations

import logging
from typing import List

from openpup.agent_host import AgentHost
from openpup.config import Settings
from openpup.heartbeat.scheduler import Scheduler
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry

logger = logging.getLogger("openpup.routines")


async def run_due_routines(
    host: AgentHost,
    settings: Settings,
    registry: PlatformRegistry,
    scheduler: Scheduler,
) -> List[str]:
    """Run every due routine and deliver results. Returns names that fired."""
    fired: List[str] = []
    for routine in scheduler.due():
        logger.info("Running routine '%s'", routine.name)
        try:
            output = await host.run(
                routine.prompt,
                conversation=f"__routine__:{routine.name}",
                keep_history=False,
            )
        except Exception:
            logger.exception("Routine '%s' failed", routine.name)
            continue

        output = (output or "").strip()
        if not output or "[SILENT]" in output:
            logger.debug("Routine '%s' chose silence", routine.name)
            fired.append(routine.name)
            continue

        if routine.deliver:
            await registry.send(Envelope.to(routine.deliver, output))
        fired.append(routine.name)
    return fired
