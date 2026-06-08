"""Discord adapter built on discord.py.

Listens for DMs and messages that mention the bot, converts them to Envelopes,
and sends outbound Envelopes back to the originating channel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.discord")


class DiscordAdapter(PlatformAdapter):
    name = "discord"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        if not settings.discord_bot_token:
            raise ValueError("DISCORD_BOT_TOKEN is required when discord is enabled")
        import discord  # noqa: F401  (raises ImportError if extra not installed)

        self._discord = discord
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self._client = discord.Client(intents=intents)
        self._task: Optional[asyncio.Task] = None
        self._register_events()

    def _register_events(self) -> None:
        client = self._client

        @client.event
        async def on_ready() -> None:  # pragma: no cover - needs live gateway
            logger.info("Discord connected as %s", client.user)

        @client.event
        async def on_message(message) -> None:  # pragma: no cover - needs live gateway
            if message.author == client.user:
                return
            is_dm = message.guild is None
            mentioned = client.user in getattr(message, "mentions", [])
            if not (is_dm or mentioned):
                return
            envelope = Envelope(
                platform=self.name,
                channel=str(message.channel.id),
                sender=str(message.author),
                text=message.content or "",
            )
            await self.registry.dispatch_inbound(envelope)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._client.start(self.settings.discord_bot_token))
        logger.info("Discord adapter started")

    async def stop(self) -> None:
        try:
            await self._client.close()
        finally:
            if self._task:
                self._task.cancel()
        logger.info("Discord adapter stopped")

    async def send(self, envelope: Envelope) -> None:  # pragma: no cover - needs gateway
        channel = self._client.get_channel(int(envelope.channel))
        if channel is None:
            channel = await self._client.fetch_channel(int(envelope.channel))
        for chunk in _chunk(envelope.text, 1900):
            await channel.send(chunk)


def _chunk(text: str, size: int):
    text = text or ""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]
