"""SMS adapter on Twilio.

Outbound via the Twilio REST client (run in a thread, since it's sync).
Inbound via the shared webhook server, which calls :meth:`handle_webhook`.
"""

from __future__ import annotations

import asyncio
import logging

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.sms")


class SMSAdapter(PlatformAdapter):
    name = "sms"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        if not (
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_from_number
        ):
            raise ValueError(
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER required"
            )
        from twilio.rest import Client

        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    async def start(self) -> None:
        logger.info("SMS adapter ready (inbound via webhook server)")

    async def stop(self) -> None:
        return None

    async def send(self, envelope: Envelope) -> None:
        # Twilio SMS segments long messages automatically; keep it simple.
        def _do_send() -> None:
            self._client.messages.create(
                to=envelope.channel,
                from_=self.settings.twilio_from_number,
                body=envelope.text[:1500],
            )

        await asyncio.to_thread(_do_send)

    async def handle_webhook(self, form: dict) -> Envelope | None:
        """Convert a Twilio inbound-SMS form post into an Envelope + dispatch."""
        body = form.get("Body")
        sender = form.get("From")
        if not body or not sender:
            return None
        env = Envelope(
            platform=self.name,
            channel=sender,
            sender=sender,
            text=body,
            meta={"message_sid": form.get("MessageSid")},
        )
        await self.registry.dispatch_inbound(env)
        return env
