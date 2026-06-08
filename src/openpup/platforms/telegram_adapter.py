"""Telegram adapter built on python-telegram-bot (async, long-polling)."""

from __future__ import annotations

import logging

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.telegram")


class TelegramAdapter(PlatformAdapter):
    name = "telegram"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required when telegram is enabled")
        from telegram.ext import ApplicationBuilder, MessageHandler, filters

        self._app = ApplicationBuilder().token(settings.telegram_bot_token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        self._started = False

    async def _on_message(self, update, context) -> None:  # pragma: no cover - live
        msg = update.effective_message
        if msg is None or not msg.text:
            return
        envelope = Envelope(
            platform=self.name,
            channel=str(update.effective_chat.id),
            sender=(update.effective_user.username if update.effective_user else None),
            text=msg.text,
        )
        await self.registry.dispatch_inbound(envelope)

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        self._started = True
        logger.info("Telegram adapter started (long-polling)")

    async def stop(self) -> None:
        if not self._started:
            return
        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        finally:
            self._started = False
        logger.info("Telegram adapter stopped")

    async def send(self, envelope: Envelope) -> None:  # pragma: no cover - live
        for chunk in _chunk(envelope.text, 4000):
            await self._app.bot.send_message(chat_id=int(envelope.channel), text=chunk)


def _chunk(text: str, size: int):
    text = text or ""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]
