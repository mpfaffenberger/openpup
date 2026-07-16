"""Tests for topic delivery."""

from openpup.topic_delivery import TopicSubscriber, publish, register


class TestRegister:
    def test_register_and_publish(self, tmp_path, monkeypatch):
        """Register a console subscriber, publish, verify delivery."""
        from openpup.topics import TopicEvent, TopicBus, TopicStore

        # Use a per-test bus + store.
        bus = TopicBus()
        store = TopicStore(tmp_path / "t.json")
        sub = TopicSubscriber(topic_type="rss", target="https://hnrss.org", channel="console")
        register(sub, bus=bus, store=store)
        # Publish.
        notified = publish(
            TopicEvent(topic_type="rss", target="https://hnrss.org", ts=12345, payload={"a": 1}),
            bus=bus,
            store=store,
        )
        assert notified >= 1
        # Persistence updated last_fired_ts.
        watched = store.get("rss", "https://hnrss.org")
        assert watched.last_fired_ts == 12345
