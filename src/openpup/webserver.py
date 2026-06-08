"""Shared inbound webhook server (FastAPI) for WhatsApp + SMS.

Only started when ``OPENPUP_WEB_ENABLED=true``. Routes:

* ``GET  /webhook/whatsapp`` — Meta verification handshake
* ``POST /webhook/whatsapp`` — inbound WhatsApp messages
* ``POST /webhook/sms``      — inbound Twilio SMS (form-encoded)
* ``GET  /healthz``          — liveness probe
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from openpup.config import Settings
from openpup.messaging.registry import PlatformRegistry

logger = logging.getLogger("openpup.web")


class WebhookServer:
    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self._server = None
        self._task: Optional[asyncio.Task] = None
        self.app = self._build_app()

    def _build_app(self):
        from fastapi import FastAPI, Request, Response

        app = FastAPI(title="OpenPup Webhooks")

        @app.get("/healthz")
        async def healthz() -> dict:
            return {"ok": True, "platforms": self.registry.platforms()}

        @app.get("/webhook/whatsapp")
        async def whatsapp_verify(request: Request) -> Response:
            params = request.query_params
            mode = params.get("hub.mode")
            token = params.get("hub.verify_token")
            challenge = params.get("hub.challenge", "")
            if mode == "subscribe" and token == self.settings.whatsapp_verify_token:
                return Response(content=challenge, media_type="text/plain")
            return Response(status_code=403)

        @app.post("/webhook/whatsapp")
        async def whatsapp_inbound(request: Request) -> dict:
            adapter = self.registry.get("whatsapp")
            if adapter is None:
                return {"ok": False, "error": "whatsapp not enabled"}
            payload = await request.json()
            await adapter.handle_webhook(payload)  # type: ignore[attr-defined]
            return {"ok": True}

        @app.post("/webhook/sms")
        async def sms_inbound(request: Request) -> Response:
            adapter = self.registry.get("sms")
            if adapter is None:
                return Response(status_code=404)
            form = dict(await request.form())
            await adapter.handle_webhook(form)  # type: ignore[attr-defined]
            # Twilio expects TwiML; empty response = no auto-reply.
            return Response(
                content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
                media_type="application/xml",
            )

        return app

    async def start(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            self.app,
            host=self.settings.web_host,
            port=self.settings.web_port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        logger.info(
            "Webhook server listening on %s:%s",
            self.settings.web_host,
            self.settings.web_port,
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task:
            self._task.cancel()
        logger.info("Webhook server stopped")
