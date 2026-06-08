"""Platform adapter registry + unified delivery.

Adapters register themselves here at startup. The registry routes outbound
envelopes to the right adapter and fans inbound envelopes out to a single
async handler (the runtime). Inspired by hermes-agent's delivery/registry
split, but intentionally tiny.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict, List, Optional

from openpup.messaging.envelope import Envelope

logger = logging.getLogger("openpup.registry")

InboundHandler = Callable[[Envelope], Awaitable[None]]


class PlatformRegistry:
    """Holds the live platform adapters and routes messages between them."""

    def __init__(self) -> None:
        self._adapters: Dict[str, "object"] = {}
        self._inbound_handler: Optional[InboundHandler] = None

    # ---- registration ----------------------------------------------------
    def register(self, adapter: "object") -> None:
        name = getattr(adapter, "name", None)
        if not name:
            raise ValueError("Adapter must expose a 'name' attribute")
        self._adapters[name] = adapter
        logger.info("Registered platform adapter: %s", name)

    def adapters(self) -> List["object"]:
        return list(self._adapters.values())

    def get(self, name: str) -> Optional["object"]:
        return self._adapters.get(name)

    def platforms(self) -> List[str]:
        return list(self._adapters.keys())

    # ---- inbound ---------------------------------------------------------
    def set_inbound_handler(self, handler: InboundHandler) -> None:
        self._inbound_handler = handler

    async def dispatch_inbound(self, envelope: Envelope) -> None:
        """Called by adapters when a new message arrives."""
        if self._inbound_handler is None:
            logger.warning("Inbound message dropped (no handler): %s", envelope.address)
            return
        await self._inbound_handler(envelope)

    # ---- outbound --------------------------------------------------------
    async def send(self, envelope: Envelope) -> bool:
        """Route an outbound envelope to its platform adapter."""
        adapter = self._adapters.get(envelope.platform)
        if adapter is None:
            logger.error(
                "Cannot deliver to '%s' — platform not registered/enabled.",
                envelope.platform,
            )
            return False
        try:
            await adapter.send(envelope)  # type: ignore[attr-defined]
            return True
        except Exception:
            logger.exception("Delivery failed on platform %s", envelope.platform)
            return False


_REGISTRY: Optional[PlatformRegistry] = None


def get_registry() -> PlatformRegistry:
    """Return the process-wide registry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = PlatformRegistry()
    return _REGISTRY
