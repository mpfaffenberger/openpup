"""Telegram adapter built on python-telegram-bot (async, long-polling)."""

from __future__ import annotations

import logging

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.telegram")


def _chat_type(update) -> str:
    """Return 'group' for groups/channels, 'dm' otherwise (default)."""
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return "dm"
    ct = (getattr(chat, "type", None) or "").lower()
    if ct in ("group", "supergroup", "channel"):
        return "group"
    return "dm"


def _mentions(msg) -> list[str]:
    """Extract user IDs from text_mention entities + mentions (text_mention only)."""
    out: list[str] = []
    for ent in (getattr(msg, "entities", None) or []):
        t = getattr(ent, "type", None)
        if t == "text_mention":
            user = getattr(ent, "user", None)
            if user is not None and getattr(user, "id", None) is not None:
                out.append(str(user.id))
    return out


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

    async def _on_message(self, update, context) -> None:
        msg = update.effective_message
        if msg is None or not msg.text:
            return
        user = update.effective_user
        # Telegram usernames are often absent; build a stable display name from
        # the always-present first/last name, and keep the numeric id as the
        # stable identifier.
        name = None
        sender_id = None
        if user is not None:
            name = (
                getattr(user, "full_name", None)
                or getattr(user, "username", None)
                or (str(user.id) if getattr(user, "id", None) else None)
            )
            sender_id = str(user.id) if getattr(user, "id", None) else None
        envelope = Envelope(
            platform=self.name,
            channel=str(update.effective_chat.id),
            sender=name,
            sender_id=sender_id,
            text=msg.text,
            chat_type=_chat_type(update),
            mentions=_mentions(msg),
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

    async def typing(self, channel: str) -> None:
        """Show the Telegram 'typing...' action so the user knows the pup is
        working -- especially during slow runs / transient-error retries, which
        would otherwise look like dead silence. The action auto-expires after a
        few seconds, so the runtime re-pokes it on a keepalive loop.
        """
        from telegram.constants import ChatAction

        await self._app.bot.send_chat_action(chat_id=int(channel), action=ChatAction.TYPING)


def _chunk(text: str, size: int):
    text = text or ""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]
