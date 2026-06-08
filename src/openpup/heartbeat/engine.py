"""The heartbeat engine: one async loop, jittered ticks, four behaviors."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional

from openpup.agent_host import AgentHost
from openpup.config import Settings
from openpup.heartbeat import outreach, reflect, routines
from openpup.heartbeat.scheduler import Scheduler
from openpup.messaging.registry import PlatformRegistry

logger = logging.getLogger("openpup.heartbeat")


class Heartbeat:
    """Drives OpenPup's periodic 'consciousness' tick."""

    def __init__(
        self,
        host: AgentHost,
        settings: Settings,
        registry: PlatformRegistry,
        scheduler: Optional[Scheduler] = None,
    ) -> None:
        self.host = host
        self.settings = settings
        self.registry = registry
        self.scheduler = scheduler or Scheduler.load(settings.state_dir / "routines.json")
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.tick_count = 0
        self.last_tick: float = 0.0

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        if not self.settings.heartbeat_enabled:
            logger.info("Heartbeat disabled by config")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Heartbeat started: every %ss (+/-%ss), behaviors=%s",
            self.settings.heartbeat_interval,
            self.settings.heartbeat_jitter,
            self.settings.behaviors,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
        logger.info("Heartbeat stopped after %d ticks", self.tick_count)

    # ---- loop ------------------------------------------------------------
    def _next_delay(self) -> float:
        jitter = random.uniform(-self.settings.heartbeat_jitter, self.settings.heartbeat_jitter)
        return max(5.0, self.settings.heartbeat_interval + jitter)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._next_delay())
                break  # stop was set
            except asyncio.TimeoutError:
                pass
            await self.tick()

    async def tick(self) -> None:
        """Run one heartbeat tick: every enabled behavior, fault-isolated."""
        self.tick_count += 1
        self.last_tick = time.time()
        behaviors = self.settings.behaviors
        logger.debug("Heartbeat tick #%d: %s", self.tick_count, behaviors)

        if "inbound" in behaviors:
            await self._safe(self._poll_inbound(), "inbound")
        if "routines" in behaviors:
            await self._safe(
                routines.run_due_routines(self.host, self.settings, self.registry, self.scheduler),
                "routines",
            )
        if "reflect" in behaviors:
            await self._safe(reflect.reflect(self.host, self.settings), "reflect")
        if "outreach" in behaviors:
            await self._safe(
                outreach.maybe_reach_out(self.host, self.settings, self.registry),
                "outreach",
            )

    async def _poll_inbound(self) -> None:
        """Tick poll-based adapters (e.g. email) so they fetch new messages."""
        for adapter in self.registry.adapters():
            poll = getattr(adapter, "poll_once", None)
            if poll is None:
                continue
            try:
                await poll()
            except Exception:
                logger.exception("poll_once failed for %s", getattr(adapter, "name", "?"))

    @staticmethod
    async def _safe(coro, label: str) -> None:
        try:
            await coro
        except Exception:
            logger.exception("Heartbeat behavior '%s' raised", label)
