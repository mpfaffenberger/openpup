"""Common adapter interface + the factory that wires up enabled platforms."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry

logger = logging.getLogger("openpup.platforms")


class PlatformAdapter(ABC):
    """Lifecycle + send/receive contract every platform must satisfy.

    Inbound messages are delivered by calling
    ``self.registry.dispatch_inbound(envelope)``. Outbound messages arrive via
    ``send(envelope)``. ``start()`` / ``stop()`` manage long-lived connections.
    """

    #: stable platform name, matches ``Envelope.platform`` and config prefixes
    name: str = "base"

    def __init__(self, settings: Settings, registry: PlatformRegistry) -> None:
        self.settings = settings
        self.registry = registry

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for inbound messages (connect / start polling)."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down connections cleanly."""

    @abstractmethod
    async def send(self, envelope: Envelope) -> None:
        """Deliver an outbound envelope on this platform."""


def build_enabled_adapters(settings: Settings, registry: PlatformRegistry) -> List[PlatformAdapter]:
    """Instantiate adapters that are enabled in config + importable.

    Missing optional dependencies are logged and skipped rather than fatal, so
    you can run with just the platforms you've installed extras for.
    """
    adapters: List[PlatformAdapter] = []

    builders = [
        (settings.discord_enabled, _build_discord),
        (settings.telegram_enabled, _build_telegram),
        (settings.whatsapp_enabled, _build_whatsapp),
        (settings.email_enabled, _build_email),
        (settings.sms_enabled, _build_sms),
    ]

    for enabled, builder in builders:
        if not enabled:
            continue
        try:
            adapter = builder(settings, registry)
        except ImportError as exc:
            logger.warning("Skipping a platform — missing dependency: %s", exc)
            continue
        except Exception:
            logger.exception("Failed to build a platform adapter")
            continue
        if adapter is not None:
            registry.register(adapter)
            adapters.append(adapter)

    return adapters


def _build_discord(settings: Settings, registry: PlatformRegistry) -> PlatformAdapter:
    from openpup.platforms.discord_adapter import DiscordAdapter

    return DiscordAdapter(settings, registry)


def _build_telegram(settings: Settings, registry: PlatformRegistry) -> PlatformAdapter:
    from openpup.platforms.telegram_adapter import TelegramAdapter

    return TelegramAdapter(settings, registry)


def _build_whatsapp(settings: Settings, registry: PlatformRegistry) -> PlatformAdapter:
    from openpup.platforms.whatsapp_adapter import WhatsAppAdapter

    return WhatsAppAdapter(settings, registry)


def _build_email(settings: Settings, registry: PlatformRegistry) -> PlatformAdapter:
    from openpup.platforms.email_adapter import EmailAdapter

    return EmailAdapter(settings, registry)


def _build_sms(settings: Settings, registry: PlatformRegistry) -> PlatformAdapter:
    from openpup.platforms.sms_adapter import SMSAdapter

    return SMSAdapter(settings, registry)
