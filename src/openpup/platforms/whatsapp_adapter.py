"""WhatsApp adapter on the Meta WhatsApp Cloud API.

Outbound messages are sent via the Graph API with httpx. Inbound messages
arrive through the shared webhook server (see ``openpup.webserver``), which
calls :meth:`handle_webhook` to convert payloads into Envelopes.
"""

from __future__ import annotations

import logging
from typing import List

import httpx

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.whatsapp")

_GRAPH = "https://graph.facebook.com/v19.0"


class WhatsAppAdapter(PlatformAdapter):
    name = "whatsapp"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        if not (settings.whatsapp_phone_number_id and settings.whatsapp_access_token):
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN are required")
        self._client = httpx.AsyncClient(timeout=30)

    async def start(self) -> None:
        # Inbound is webhook-driven; nothing to poll.
        logger.info("WhatsApp adapter ready (inbound via webhook server)")

    async def stop(self) -> None:
        await self._client.aclose()

    async def send(self, envelope: Envelope) -> None:
        url = f"{_GRAPH}/{self.settings.whatsapp_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.settings.whatsapp_access_token}"}
        for chunk in _chunk(envelope.text, 4000):
            payload = {
                "messaging_product": "whatsapp",
                "to": envelope.channel,
                "type": "text",
                "text": {"body": chunk},
            }
            resp = await self._client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("WhatsApp send failed %s: %s", resp.status_code, resp.text)

    async def handle_webhook(self, payload: dict) -> List[Envelope]:
        """Parse a WhatsApp webhook payload into inbound Envelopes + dispatch."""
        envelopes: List[Envelope] = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        if msg.get("type") != "text":
                            continue
                        env = Envelope(
                            platform=self.name,
                            channel=msg.get("from", ""),
                            sender=msg.get("from"),
                            text=msg.get("text", {}).get("body", ""),
                            meta={"wamid": msg.get("id")},
                        )
                        envelopes.append(env)
        except Exception:
            logger.exception("Failed to parse WhatsApp webhook payload")
        for env in envelopes:
            await self.registry.dispatch_inbound(env)
        return envelopes


def _chunk(text: str, size: int):
    text = text or ""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]
