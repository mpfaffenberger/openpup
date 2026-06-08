"""The normalized message envelope shared by every platform adapter.

Inbound messages from Discord/Telegram/WhatsApp/Email/SMS are converted *into*
an ``Envelope``; outbound replies and proactive pings are expressed *as* an
``Envelope`` and handed to the registry for delivery. This decouples the agent
and heartbeat from any platform-specific SDK.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Envelope(BaseModel):
    """A single message moving in or out of OpenPup."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    direction: Direction = Direction.INBOUND
    platform: str = ""
    # Where the message lives (chat id, channel id, phone number, email thread).
    channel: str = ""
    # Who sent it (inbound) — display name or handle.
    sender: Optional[str] = None
    # Optional reply/thread anchor for platforms that support threads.
    thread_id: Optional[str] = None
    text: str = ""
    # Free-form attachment descriptors (urls, file paths, mime types).
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    # Platform-specific extras (subject line, message ids, etc.).
    meta: Dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)

    @property
    def address(self) -> str:
        """Canonical ``platform:channel`` address string."""
        return f"{self.platform}:{self.channel}"

    def reply(self, text: str, **meta: Any) -> "Envelope":
        """Build an outbound envelope addressed back at this message's sender."""
        return Envelope(
            direction=Direction.OUTBOUND,
            platform=self.platform,
            channel=self.channel,
            thread_id=self.thread_id,
            text=text,
            meta={**self.meta, **meta},
        )

    @staticmethod
    def to(address: str, text: str, **meta: Any) -> "Envelope":
        """Build an outbound envelope to a ``platform:channel`` address."""
        platform, _, channel = address.partition(":")
        return Envelope(
            direction=Direction.OUTBOUND,
            platform=platform,
            channel=channel,
            text=text,
            meta=meta,
        )
