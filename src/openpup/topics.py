"""Topic subscriptions: a lightweight pub/sub primitive.

Owners can subscribe to topics (RSS feeds, GitHub repos, calendar event
horizons, file paths, etc.) and get notified when events fire. The bus itself
is in-process; persistence is via ``~/.openpup/topics.json``.

This module is just the bus + persistence. Publishers (RSS pollers, GitHub
pollers, ...) live elsewhere and emit events. Subscribers (delivery to the
owner's channel) also live elsewhere; the bus just routes.

A "topic" is identified by a type + target string (e.g. ``("rss",
"https://hnrss.org/frontpage")``).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("openpup.topics")

DEFAULT_STORE = "topics.json"


@dataclass
class TopicEvent:
    topic_type: str
    target: str
    ts: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopicSubscription:
    topic_type: str
    target: str
    last_fired_ts: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def key(self) -> tuple[str, str]:
        return (self.topic_type, self.target)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "TopicSubscription":
        return cls(
            topic_type=str(raw["topic_type"]),
            target=str(raw["target"]),
            last_fired_ts=int(raw.get("last_fired_ts", 0)),
            created_at=int(raw.get("created_at", time.time())),
        )


# ---------------------------------------------------------------------------
# In-memory bus (thread-safe)
# ---------------------------------------------------------------------------
class TopicBus:
    """Thread-safe pub/sub for TopicEvent."""

    def __init__(self) -> None:
        self._listeners: dict[tuple[str, str], list[Callable[[TopicEvent], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(
        self, topic_type: str, target: str, fn: Callable[[TopicEvent], None]
    ) -> None:
        key = (topic_type, target)
        with self._lock:
            self._listeners.setdefault(key, []).append(fn)

    def publish(self, event: TopicEvent) -> int:
        """Notify subscribers of an event. Returns the count of subscribers called."""
        key = (event.topic_type, event.target)
        with self._lock:
            subs = list(self._listeners.get(key, []))
        for fn in subs:
            try:
                fn(event)
            except Exception:
                logger.exception("subscriber raised")
        return len(subs)


# ---------------------------------------------------------------------------
# Persistent subscription store
# ---------------------------------------------------------------------------
class TopicStore:
    """JSON-backed store of subscriptions (registered topics + last_fired)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, TopicSubscription]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            logger.exception("could not read topics file %s", self.path)
            return {}
        out: dict[str, TopicSubscription] = {}
        for s in raw.get("subscriptions", []):
            sub = TopicSubscription.from_dict(s)
            out[sub.key] = sub
        return out

    def _save(self, subs: dict[str, TopicSubscription]) -> None:
        out = {
            "subscriptions": [
                s.to_dict() for k, s in subs.items()
            ]
        }
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def list(self) -> list[TopicSubscription]:
        return sorted(self._load().values(), key=lambda s: (s.topic_type, s.target))

    def get(self, topic_type: str, target: str) -> Optional[TopicSubscription]:
        return self._load().get((topic_type, target))

    def subscribe(self, topic_type: str, target: str) -> TopicSubscription:
        subs = self._load()
        key = (topic_type, target)
        if key not in subs:
            subs[key] = TopicSubscription(topic_type=topic_type, target=target)
            self._save(subs)
        return subs[key]

    def unsubscribe(self, topic_type: str, target: str) -> bool:
        subs = self._load()
        key = (topic_type, target)
        if key in subs:
            del subs[key]
            self._save(subs)
            return True
        return False

    def touch(self, topic_type: str, target: str, ts: Optional[int] = None) -> None:
        """Update last_fired_ts after a publisher emits."""
        subs = self._load()
        key = (topic_type, target)
        if key in subs:
            subs[key].last_fired_ts = ts or int(time.time())
            self._save(subs)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> TopicStore:
    return TopicStore(default_store_path())


# Process-wide bus. Tests can replace this with a fresh instance.
_bus = TopicBus()


def get_bus() -> TopicBus:
    global _bus
    return _bus
