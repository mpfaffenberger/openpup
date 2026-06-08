"""The OpenPup runtime: boots everything and runs the central async loop.

Wiring order:
  1. settings + agent host (boots code-puppy plugins incl. puppy_kennel memory)
  2. platform adapters (only the enabled + installed ones)
  3. inbound handler: route every inbound Envelope through the agent and reply
  4. heartbeat (consciousness) + optional webhook server
  5. supervise until shutdown, then tear everything down cleanly
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from openpup import memory
from openpup.agent_host import AgentHost
from openpup.config import Settings, get_settings
from openpup.heartbeat.engine import Heartbeat
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import get_registry
from openpup.platforms.base import PlatformAdapter, build_enabled_adapters

logger = logging.getLogger("openpup.runtime")


class OpenPup:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.registry = get_registry()
        self.host = AgentHost(agent_name=self.settings.agent, default_model=self.settings.model)
        self.adapters: List[PlatformAdapter] = []
        self.heartbeat: Optional[Heartbeat] = None
        self.webserver = None
        self._stop = asyncio.Event()

    # ---- inbound handling ------------------------------------------------
    async def handle_inbound(self, envelope: Envelope) -> None:
        """Route an inbound message to the agent and reply on the same channel."""
        logger.info("Inbound from %s (%s)", envelope.address, envelope.sender)
        try:
            reply = await self.host.run(envelope.text, conversation=envelope.address)
        except Exception:
            logger.exception("Agent failed handling inbound message")
            reply = "Sorry — I hit an error processing that."

        if reply and reply.strip():
            await self.registry.send(envelope.reply(reply))
        # Record the exchange for the heartbeat's memory-driven behaviors.
        memory.remember(
            f"[{envelope.platform}] {envelope.sender}: {envelope.text}\n-> {reply}",
            wing=memory.AGENT_WING,
            room="conversations",
        )

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        logger.info("Booting %s ...", self.settings.name)
        await self.host.boot()

        self.registry.set_inbound_handler(self.handle_inbound)
        self.adapters = build_enabled_adapters(self.settings, self.registry)
        logger.info("Enabled platforms: %s", self.registry.platforms() or "(none)")

        for adapter in self.adapters:
            await adapter.start()

        if self.settings.web_enabled:
            from openpup.webserver import WebhookServer

            self.webserver = WebhookServer(self.settings, self.registry)
            await self.webserver.start()

        self.heartbeat = Heartbeat(self.host, self.settings, self.registry)
        await self.heartbeat.start()

        logger.info("%s is awake. ", self.settings.name)

    async def stop(self) -> None:
        logger.info("Shutting down ...")
        if self.heartbeat:
            await self.heartbeat.stop()
        if self.webserver:
            await self.webserver.stop()
        for adapter in self.adapters:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("Error stopping adapter")
        await self.host.shutdown()
        self._stop.set()

    async def run_forever(self) -> None:
        await self.start()
        try:
            await self._stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def request_stop(self) -> None:
        self._stop.set()
