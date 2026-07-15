"""The heartbeat engine: one async loop, jittered ticks, four behaviors."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional

from openpup.agent_host import AgentHost
from openpup.config import Settings
from openpup.heartbeat import curator, outreach, reflect, routines
from openpup.heartbeat.scheduler import Scheduler, get_scheduler
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
        # Shared singleton so jobs the agent schedules are picked up live.
        self.scheduler = scheduler or get_scheduler()
        self._task: Optional[asyncio.Task] = None
        self._fast_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.tick_count = 0
        self.fast_tick_count = 0
        self.last_tick: float = 0.0

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        if not self.settings.heartbeat_enabled:
            logger.info("Heartbeat disabled by config")
            return
        self._stop.clear()
        # Slow loop: reflect + outreach (the 'thinking' behaviors).
        self._task = asyncio.create_task(self._loop())
        # Fast loop: scheduler + inbound polling, so reminders/jobs fire on time.
        self._fast_task = asyncio.create_task(self._fast_loop())
        logger.info(
            "Heartbeat started: reflect/outreach every %ss (+/-%ss); scheduler+inbound "
            "every %ss; behaviors=%s",
            self.settings.heartbeat_interval,
            self.settings.heartbeat_jitter,
            self.settings.scheduler_interval,
            self.settings.behaviors,
        )

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._task, self._fast_task):
            if task:
                task.cancel()
        logger.info("Heartbeat stopped after %d ticks", self.tick_count)

    # ---- loops -----------------------------------------------------------
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

    async def _fast_loop(self) -> None:
        interval = max(5, self.settings.scheduler_interval)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break  # stop was set
            except asyncio.TimeoutError:
                pass
            await self.fast_tick()

    async def fast_tick(self) -> None:
        """Frequent, cheap tick: fire due scheduled jobs + poll inbound."""
        self.fast_tick_count += 1
        from openpup import access

        access.set_current_role(access.OWNER)
        behaviors = self.settings.behaviors
        if "inbound" in behaviors:
            await self._safe(self._poll_inbound(), "inbound")
        if "routines" in behaviors:
            await self._safe(
                routines.run_due_routines(self.host, self.settings, self.registry, self.scheduler),
                "routines",
            )

    async def tick(self) -> None:
        """Run one (slow) heartbeat tick: every enabled behavior, fault-isolated.

        Includes the fast behaviors too, so a manual ``tick()`` (tests / CLI)
        still exercises everything.
        """
        self.tick_count += 1
        self.last_tick = time.time()
        # Heartbeat behaviors act on the owner's behalf -> owner privileges,
        # so agent runs here may use owner-only tools (email, messaging).
        from openpup import access

        access.set_current_role(access.OWNER)
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
        if "curator" in behaviors:
            # Opt-in, and internally interval-gated to ~weekly runs.
            await self._safe(curator.maybe_curate(self.host, self.settings), "curator")
        if "briefings" in behaviors:
            # Opt-in RSS / Atom digest delivery.
            from openpup.heartbeat import briefings

            await self._safe(briefings.briefings(self.host, self.settings, self.registry), "briefings")

    async def _poll_inbound(self) -> None:
        """Tick poll-based chat adapters (e.g. iMessage) so they fetch new
        messages. Email is intentionally excluded: it's a read-only sensor with
        no ``poll_once``, so it's never crawled here."""
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
