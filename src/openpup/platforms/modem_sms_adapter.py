"""SMS via host-side SMS Bridge HTTP API.

The host runs sms_bridge.py which talks to ModemManager via mmcli.
This adapter calls the bridge over HTTP for send/receive.

Config:
    SMS_ENABLED=true
    SMS_BACKEND=modem
    MODEM_BRIDGE_URL=http://127.0.0.1:9081   # defaults to this
    MODEM_SMS_MAX_CHARS=1500
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.platforms.base import PlatformAdapter

logger = logging.getLogger("openpup.modem_sms")

TRUNCATION_NOTICE = "\n[truncated]"


def _bounded_sms_text(text: str, max_chars: int) -> str:
    """Apply the configured safety cap without silently hiding truncation."""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(TRUNCATION_NOTICE):
        return text[:max_chars]
    body_limit = max_chars - len(TRUNCATION_NOTICE)
    return text[:body_limit].rstrip() + TRUNCATION_NOTICE


class ModemSMSAdapter(PlatformAdapter):
    """Send/receive SMS via the host-side sms_bridge HTTP API."""

    name = "sms"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        super().__init__(settings, registry)
        self.bridge_url = (settings.modem_bridge_url or "http://127.0.0.1:9081").rstrip("/")
        self._client = httpx.AsyncClient(timeout=15)
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        self._seen_ids: set = set()

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        # Health check
        try:
            resp = await self._client.get(f"{self.bridge_url}/health")
            resp.raise_for_status()
            info = resp.json()
            if not info.get("modem"):
                logger.warning("sms_bridge says no modem detected!")
            else:
                logger.info("sms_bridge connected, modem OK")
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot reach sms_bridge at {self.bridge_url}. "
                "Is sms_bridge.py running on the host?"
            )
        except Exception as e:
            logger.warning("sms_bridge health check issue: %s", e)

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_inbound_loop())
        logger.info("Modem SMS adapter ready (bridge=%s)", self.bridge_url)

    async def stop(self) -> None:
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()

    # ── send ───────────────────────────────────────────────────────────

    async def send(self, envelope: Envelope) -> None:
        text = _bounded_sms_text(envelope.text, self.settings.modem_sms_max_chars)
        recipient = envelope.channel
        logger.info(
            "Sending SMS to %s via bridge (%d chars; ModemManager handles multipart)",
            recipient,
            len(text),
        )

        resp = await self._client.post(
            f"{self.bridge_url}/sms/send",
            json={"number": recipient, "text": text},
        )
        resp.raise_for_status()
        logger.info("SMS sent: %s", resp.json())

    # ── inbound polling ────────────────────────────────────────────────

    async def _poll_inbound_loop(self) -> None:
        interval = self.settings.scheduler_interval or 30
        while self._running:
            try:
                await self._check_new_sms()
                if self.settings.mms_enabled:
                    await self._check_new_mms()
            except Exception:
                logger.exception("error polling modem bridge")
            await asyncio.sleep(interval)

    async def _check_new_sms(self) -> None:
        """Poll sms_bridge for new inbound messages."""
        try:
            resp = await self._client.get(f"{self.bridge_url}/sms/inbox")
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError:
            logger.warning("sms_bridge unreachable")
            return
        except Exception:
            return

        for msg in data.get("messages", []):
            sender = msg.get("sender", "")
            body = msg.get("text", "")
            if not sender or not body:
                continue

            msg_id = f"{sender}:{msg.get('path', '')}"
            if msg_id in self._seen_ids:
                continue
            self._seen_ids.add(msg_id)

            env = Envelope(
                platform=self.name,
                channel=sender,
                sender=sender,
                text=body,
            )
            logger.info("Inbound SMS from %s: %s", sender, body[:80])
            await self.registry.dispatch_inbound(env)

    async def _check_new_mms(self) -> None:
        """Poll the bridge for completed MMS messages and acknowledge delivery."""
        try:
            resp = await self._client.get(f"{self.bridge_url}/mms/inbox")
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError:
            logger.warning("MMS bridge unreachable")
            return
        except Exception:
            logger.debug("MMS poll failed", exc_info=True)
            return

        for msg in data.get("messages", []):
            message_id = str(msg.get("id", ""))
            sender = str(msg.get("sender", ""))
            if not message_id or not sender:
                continue
            dedupe_id = f"mms:{message_id}"
            if dedupe_id in self._seen_ids:
                continue

            env = Envelope(
                platform=self.name,
                channel=sender,
                sender=sender,
                text=str(msg.get("text", "Sent an image via MMS.")),
                attachments=list(msg.get("attachments", [])),
                meta={"mms_id": message_id, "mms_date": msg.get("date", "")},
            )
            logger.info(
                "Inbound MMS from %s with %d attachment(s)",
                sender,
                len(env.attachments),
            )
            await self.registry.dispatch_inbound(env)
            ack = await self._client.post(
                f"{self.bridge_url}/mms/ack",
                json={"id": message_id},
            )
            ack.raise_for_status()
            self._seen_ids.add(dedupe_id)
