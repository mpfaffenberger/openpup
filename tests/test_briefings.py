"""Tests for the news briefings heartbeat behavior.

Covers feed parsing (RSS + Atom), config/state helpers, quiet-hours guard,
digest rendering, and the end-to-end delivery flow with a mocked adapter.
"""

import json

import pytest

from openpup.heartbeat import briefings
from openpup.heartbeat.briefings import (
    FeedItem,
    _in_quiet_hours,
    _parse,
    _parse_feeds,
    _render_digest,
    briefings as run_briefings,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hacker News</title>
    <link>https://news.ycombinator.com/</link>
    <item>
      <title>Old post</title>
      <link>https://example.com/old</link>
      <pubDate>Mon, 15 Jan 2024 12:00:00 +0000</pubDate>
      <description>old content</description>
    </item>
    <item>
      <title>New post</title>
      <link>https://example.com/new</link>
      <pubDate>Mon, 15 Jan 2024 13:00:00 +0000</pubDate>
      <description>new content</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv cs.AI</title>
  <entry>
    <title>Atom paper</title>
    <link href="https://arxiv.org/abs/1234.5678"/>
    <updated>2024-02-01T10:00:00Z</updated>
    <summary>summary of paper</summary>
  </entry>
</feed>
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class TestParse:
    def test_parse_rss(self):
        items = _parse(SAMPLE_RSS)
        assert len(items) == 2
        # Items are newest-first is NOT guaranteed; both have a published_ts.
        for it in items:
            assert it.link.startswith("https://")
            assert it.title
            assert it.published_ts > 0

    def test_parse_atom(self):
        items = _parse(SAMPLE_ATOM)
        assert len(items) == 1
        assert items[0].title == "Atom paper"
        assert items[0].link == "https://arxiv.org/abs/1234.5678"

    def test_parse_handles_no_dates(self):
        no_date = """<rss version="2.0"><channel>
            <item><title>x</title><link>https://e/</link></item>
        </channel></rss>"""
        items = _parse(no_date)
        assert len(items) == 1
        assert items[0].published_ts == 0.0

    def test_strip_html(self):
        assert briefings._strip("<p>hello <b>world</b></p>") == "hello world"
        assert briefings._strip("plain") == "plain"


class TestParseDate:
    def test_rfc822(self):
        # parsed via email.utils.parsedate_to_datetime
        ts = briefings._parse_date("Mon, 15 Jan 2024 12:00:00 +0000")
        # Just verify it produces a plausible epoch.
        assert ts > 1700000000  # > 2023-11
        assert ts < 1800000000

    def test_iso8601(self):
        ts = briefings._parse_date("2024-02-01T10:00:00Z")
        assert ts > 1700000000

    def test_empty_returns_zero(self):
        assert briefings._parse_date("") == 0.0
        assert briefings._parse_date(None) == 0.0
        assert briefings._parse_date("garbage") == 0.0


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
class TestParseFeedsSpec:
    def test_empty(self):
        assert _parse_feeds("") == []

    def test_single(self):
        assert _parse_feeds("https://hnrss.org/frontpage") == ["https://hnrss.org/frontpage"]

    def test_multiple_with_whitespace(self):
        feeds = _parse_feeds(" https://a , https://b ,,https://c  ")
        assert feeds == ["https://a", "https://b", "https://c"]

    def test_filters_non_http(self):
        # file:// is rejected.
        feeds = _parse_feeds("file:///tmp/x, https://b")
        assert feeds == ["https://b"]


# ---------------------------------------------------------------------------
# Quiet hours guard
# ---------------------------------------------------------------------------
class TestQuietHours:
    def test_normal_window(self):
        from openpup.config import Settings

        s = Settings(_env_file=None, OPENPUP_QUIET_HOURS="22-7")
        # Force UTC for stable math.
        import os
        import time

        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        try:
            # 2024-01-15 12:00 UTC = 1705320000
            noon = 1705320000
            assert _in_quiet_hours(s, noon) is False
            # 23:00 UTC same day = 1705320000 + 11*3600 = 1705359600
            night = noon + 11 * 3600
            assert _in_quiet_hours(s, night) is True
            # 03:00 UTC next day
            early = noon + 15 * 3600
            assert _in_quiet_hours(s, early) is True
        finally:
            if old_tz is not None:
                os.environ["TZ"] = old_tz
                time.tzset()


# ---------------------------------------------------------------------------
# Digest rendering
# ---------------------------------------------------------------------------
class TestRenderDigest:
    def test_renders_basic(self):
        items = {
            "https://hnrss.org/frontpage": [
                FeedItem("First", "https://e/1", 100.0, "summary"),
                FeedItem("Second", "https://e/2", 200.0, ""),
            ],
        }
        body = _render_digest(items)
        assert "OpenPup briefing" in body
        assert "hnrss.org" in body
        assert "First" in body
        assert "Second" in body
        assert "Sources:" in body

    def test_renders_per_feed_section(self):
        items = {
            "https://hnrss.org/frontpage": [],
            "https://arxiv.org/list/cs.AI/new": [
                FeedItem("A paper", "https://arxiv.org/abs/1", 100.0, "")
            ],
        }
        # Empty feed (no new) shouldn't render a header.
        body = _render_digest(items)
        assert "hnrss.org" not in body
        assert "arxiv.org" in body
        assert "A paper" in body


# ---------------------------------------------------------------------------
# End-to-end (mocked network + adapter)
# ---------------------------------------------------------------------------
class TestBriefingsE2E:
    @pytest.mark.asyncio
    async def test_delivers_digest_on_first_run(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        from openpup.config import Settings

        s = Settings(
            _env_file=None,
            OPENPUP_HEARTBEAT_BEHAVIORS="briefings",
            OPENPUP_BRIEFING_FEEDS="https://hnrss.org/frontpage",
            OPENPUP_QUIET_HOURS="",  # never quiet
            OPENPUP_OWNER_ADDRESS="telegram:me",
            OPENPUP_HEARTBEAT_JITTER=0,
        )
        # state_dir is computed from OPENPUP_HOME, so it should be tmp_path-derived.

        # Bypass send_policy — bypass the config-DB that may have 'contacts'.
        from openpup.governance import SendDecision

        class AllowAll:
            def check(self, address, directory=None, now=None):
                return SendDecision(allowed=True, reason="")

        monkeypatch.setattr("openpup.heartbeat.briefings.get_send_policy", lambda: AllowAll())

        # Mock httpx fetch to return our RSS payload.
        class FakeResp:
            status_code = 200

            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url):
                return FakeResp(SAMPLE_RSS)

        # Replace httpx.AsyncClient globally for the duration of the call.
        monkeypatch.setattr("openpup.heartbeat.briefings.httpx.AsyncClient", FakeClient)

        # Mock registry.send so we capture the delivery.
        sent = []

        class FakeRegistry:
            async def send(self, env):
                sent.append(env)
                return True

        # Run the coroutine.
        # settings.behaviors is computed from heartbeat_behaviors.
        # We need to bypass the @asyncio coroutine + env imports.

        await run_briefings(host=None, settings=s, registry=FakeRegistry())

        assert len(sent) == 1
        env = sent[0]
        assert env.platform == "telegram"
        assert env.channel == "me"
        # The digest should mention hnrss + at least one new item.
        assert "OpenPup briefing" in env.text
        # And the state file should now exist with a last_delivered stamp.
        state_path = tmp_path / "briefings_seen.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert "_last_delivered" in state
        assert "https://hnrss.org/frontpage" in state

    @pytest.mark.asyncio
    async def test_throttled_when_recent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        from openpup.config import Settings

        s = Settings(
            _env_file=None,
            OPENPUP_HEARTBEAT_BEHAVIORS="briefings",
            OPENPUP_BRIEFING_FEEDS="https://hnrss.org/frontpage",
            OPENPUP_QUIET_HOURS="",
            OPENPUP_OWNER_ADDRESS="telegram:me",
        )
        # Bypass send_policy.
        from openpup.governance import SendDecision

        class AllowAll:
            def check(self, address, directory=None, now=None):
                return SendDecision(allowed=True, reason="")

        monkeypatch.setattr("openpup.heartbeat.briefings.get_send_policy", lambda: AllowAll())

        # Pre-populate state showing a recent last_delivered.
        state_path = tmp_path / "briefings_seen.json"
        import time as _time

        state_path.write_text(json.dumps({"_last_delivered": _time.time()}))

        # Mock fetch to avoid network.
        class FakeResp:
            status_code = 200
            text = SAMPLE_RSS

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def get(self, url):
                return FakeResp()

        monkeypatch.setattr("openpup.heartbeat.briefings.httpx.AsyncClient", FakeClient)

        sent = []

        class FakeRegistry:
            async def send(self, env):
                sent.append(env)
                return True

        await run_briefings(host=None, settings=s, registry=FakeRegistry())
        # Throttled, so no delivery.
        assert sent == []
