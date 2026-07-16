"""Topic subscribers: actual delivery wiring for the pub/sub bus.

Wraps the existing ``topics.py`` bus with a thin layer that publishes
events on the bus and registers subscribers that deliver to the owner's
preferred channel. v1 ships with a console subscriber so the framework
is testable end-to-end; channel-specific delivery (email, Telegram,
Discord, ...) is layered on in follow-up commits.

Storage: ``~/.openpup/topic_deliveries.json`` remembers which subscriptions
are active so the heartbeat can replay on startup.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from openpup.topics import TopicBus, TopicEvent, TopicSubscription, TopicStore

logger = logging.getLogger("openpup.topic_delivery")


@dataclass
class TopicSubscriber:
    """A subscriber wired to a delivery target.

    v1 ships with ``console`` only -- it logs the event to the module
    logger so tests can verify delivery.
    """

    topic_type: str
    target: str  # for type 'rss' this is a URL; for 'webhook' it's the URL
    channel: str = "console"  # 'console' | 'webhook' | (more later)

    def deliver(self, event: TopicEvent) -> None:
        """Dispatch one event to this subscriber's channel."""
        if self.channel == "console":
            logger.info(
                "[%s/%s] %s -> %s",
                event.topic_type,
                event.target,
                event.ts,
                event.payload,
            )
        elif self.channel == "webhook":
            # A real webhook dispatch lives in a follow-up commit.
            logger.info("webhook deliver %r -> %r", event.topic_type, event.target)
        else:
            raise ValueError(f"unknown channel {self.channel!r}")


def register(
    subscriber: TopicSubscriber,
    *,
    bus: TopicBus | None = None,
    store: TopicStore | None = None,
) -> None:
    """Register ``subscriber`` on the bus and ensure persistence."""
    from openpup.topics import get_bus, get_store

    bus = bus or get_bus()
    store = store or get_store()
    # Persist + bus subscribe.
    store.subscribe(subscriber.topic_type, subscriber.target)
    bus.subscribe(subscriber.topic_type, subscriber.target, subscriber.deliver)


def publish(
    event: TopicEvent,
    *,
    bus: TopicBus | None = None,
    store: TopicStore | None = None,
) -> int:
    """Publish an event: notifies subscribers and updates last_fired_ts."""
    from openpup.topics import get_bus, get_store

    bus = bus or get_bus()
    store = store or get_store()
    notified = bus.publish(event)
    store.touch(event.topic_type, event.target, ts=event.ts)
    return notified
