"""Tests for the topics (pub/sub) module."""

from pathlib import Path

import pytest

from openpup.topics import (
    TopicBus,
    TopicEvent,
    TopicStore,
    TopicSubscription,
    get_bus,
    get_store,
)


class TestSubscriptionModel:
    def test_round_trip(self):
        s = TopicSubscription(topic_type="rss", target="https://example.com/feed")
        raw = s.to_dict()
        restored = TopicSubscription.from_dict(raw)
        assert restored.topic_type == "rss"
        assert restored.target == "https://example.com/feed"


class TestTopicBus:
    def test_publish_delivers(self):
        bus = TopicBus()
        received = []

        def listener(ev):
            received.append(ev)

        bus.subscribe("rss", "https://e", listener)
        n = bus.publish(TopicEvent(topic_type="rss", target="https://e", ts=1))
        assert n == 1
        assert len(received) == 1

    def test_unknown_topic_zero_subscribers(self):
        bus = TopicBus()
        n = bus.publish(TopicEvent(topic_type="rss", target="https://e", ts=1))
        assert n == 0

    def test_subscriber_exception_doesnt_block_others(self):
        bus = TopicBus()
        results = []

        def good(ev):
            results.append("ok")

        def bad(ev):
            raise RuntimeError("nope")

        bus.subscribe("t", "x", bad)
        bus.subscribe("t", "x", good)
        n = bus.publish(TopicEvent(topic_type="t", target="x", ts=1))
        assert n == 2
        assert results == ["ok"]


class TestTopicStore:
    def test_subscribe_creates(self, tmp_path):
        s = TopicStore(tmp_path / "t.json")
        sub = s.subscribe("rss", "https://e")
        assert sub.topic_type == "rss"

    def test_subscribe_idempotent(self, tmp_path):
        s = TopicStore(tmp_path / "t.json")
        a = s.subscribe("rss", "https://e")
        b = s.subscribe("rss", "https://e")
        assert a.target == b.target

    def test_unsubscribe(self, tmp_path):
        s = TopicStore(tmp_path / "t.json")
        s.subscribe("rss", "https://e")
        assert s.unsubscribe("rss", "https://e") is True
        # Second time false.
        assert s.unsubscribe("rss", "https://e") is False

    def test_touch_updates_ts(self, tmp_path):
        s = TopicStore(tmp_path / "t.json")
        s.subscribe("rss", "https://e")
        s.touch("rss", "https://e", ts=123)
        sub = s.get("rss", "https://e")
        assert sub.last_fired_ts == 123
