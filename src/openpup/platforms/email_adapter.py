"""Email adapter: IMAP polling for inbound, SMTP for outbound.

Channels are email addresses; the subject line is carried in ``meta`` and
reused (prefixed ``Re:``) on replies. Polling runs as a background task on the
configured interval and is also tickable by the heartbeat's inbound behavior.
"""

from __future__ import annotations

import asyncio
import logging
from email.message import EmailMessage
from typing import List, Optional

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.email")


class EmailAdapter(PlatformAdapter):
    name = "email"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        required = [
            settings.email_imap_host,
            settings.email_smtp_host,
            settings.email_username,
            settings.email_password,
        ]
        if not all(required):
            raise ValueError("EMAIL_IMAP_HOST/SMTP_HOST/USERNAME/PASSWORD are required")
        # Import here so the dependency is only needed when email is enabled.
        import aiosmtplib  # noqa: F401
        from imap_tools import MailBox  # noqa: F401

        self._poll_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Email adapter started (IMAP poll every %ss)", self.settings.email_poll_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._poll_task:
            self._poll_task.cancel()
        logger.info("Email adapter stopped")

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception:
                logger.exception("Email poll failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.email_poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> List[Envelope]:
        """Fetch unseen messages, convert to Envelopes, dispatch. Tickable."""
        envelopes = await asyncio.to_thread(self._fetch_sync)
        for env in envelopes:
            await self.registry.dispatch_inbound(env)
        return envelopes

    def _fetch_sync(self) -> List[Envelope]:
        from imap_tools import AND, MailBox

        envelopes: List[Envelope] = []
        with MailBox(self.settings.email_imap_host, self.settings.email_imap_port).login(
            self.settings.email_username, self.settings.email_password
        ) as mailbox:
            for msg in mailbox.fetch(AND(seen=False), mark_seen=True):
                env = Envelope(
                    platform=self.name,
                    channel=msg.from_,
                    sender=msg.from_,
                    text=msg.text or msg.html or "",
                    meta={"subject": msg.subject, "message_id": msg.uid},
                )
                envelopes.append(env)
        return envelopes

    async def send(self, envelope: Envelope) -> None:
        import aiosmtplib

        message = EmailMessage()
        message["From"] = self.settings.email_username
        message["To"] = envelope.channel
        subject = envelope.meta.get("subject", "Message from OpenPup")
        if not str(subject).lower().startswith("re:"):
            subject = f"Re: {subject}"
        message["Subject"] = subject
        message.set_content(envelope.text)

        await aiosmtplib.send(
            message,
            hostname=self.settings.email_smtp_host,
            port=self.settings.email_smtp_port,
            username=self.settings.email_username,
            password=self.settings.email_password,
            start_tls=True,
        )
