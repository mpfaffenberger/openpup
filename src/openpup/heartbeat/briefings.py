"""News briefings heartbeat behavior.

Watches a list of RSS / Atom feeds and aggregates new items into a single
digest delivered to the owner on a configured cadence. Honors quiet hours
and a daily cap (via the outreach machinery).

Configuration (env / settings):

* ``OPENPUP_BRIEFING_FEEDS``  -- comma-separated list of feed URLs
* ``OPENPUP_BRIEFING_INTERVAL_HOURS``  -- minimum gap between digests (default 12)
* ``OPENPUP_BRIEFING_MAX_PER_DAY``  -- hard daily cap on briefings sent
  (defaults to ``OPENPUP_OUTREACH_MAX_PER_DAY``)

Adding ``briefings`` to ``OPENPUP_HEARTBEAT_BEHAVIORS`` enables the behavior.
"""
from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from openpup.agent_host import AgentHost
from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.governance import get_send_policy

logger = logging.getLogger("openpup.briefings")

DEFAULT_INTERVAL_HOURS = 12
DEFAULT_MAX_PER_DAY = 4
MIN_GAP_SECONDS = 60 * 60  # at most once an hour regardless of cadence


@dataclass
class FeedItem:
    title: str
    link: str
    published_ts: float  # epoch seconds, 0 if unknown
    summary: str


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def briefings(host: AgentHost, settings: Settings, registry: PlatformRegistry) -> None:
    """Fetch configured feeds; if anything new, deliver a digest to the owner."""
    feeds = _parse_feeds(_configured_feeds(settings))
    if not feeds:
        return

    state_file = settings.state_dir / "briefings_seen.json"
    state = _load_state(state_file)

    now = time.time()
    last_delivered = float(state.get("_last_delivered", 0.0))
    if now - last_delivered < MIN_GAP_SECONDS:
        logger.debug("briefings: throttled (last delivered %ds ago)", now - last_delivered)
        return

    new_by_feed: dict[str, list[FeedItem]] = {}
    for url in feeds:
        items = await _fetch_feed(url)
        seen_ts = float(state.get(url, 0.0))
        fresh = [it for it in items if it.published_ts and it.published_ts > seen_ts]
        if fresh:
            new_by_feed[url] = fresh

    if not any(new_by_feed.values()):
        logger.debug("briefings: nothing new across %d feeds", len(feeds))
        return

    # Quiet hours: skip (mirror outreach guard).
    if _in_quiet_hours(settings, now):
        logger.info("briefings: in quiet hours, skipping delivery (still %d new)", sum(len(v) for v in new_by_feed.values()))
        return

    digest = _render_digest(new_by_feed)
    if not settings.owner_address:
        logger.warning("briefings: no OPENPUP_OWNER_ADDRESS set; dropping digest (%d chars)", len(digest))
        return

    # Daily cap via the shared send policy (same machinery as outreach).
    decision = get_send_policy().check(settings.owner_address)
    if not decision.allowed:
        logger.info("briefings: send policy denied delivery: %s", decision.reason)
        return

    envelope = Envelope.to(settings.owner_address, digest)
    ok = await registry.send(envelope)
    if ok:
        state["_last_delivered"] = now
        for url, items in new_by_feed.items():
            if items:
                state[url] = max(it.published_ts for it in items)
        _save_state(state_file, state)
        logger.info(
            "briefings: delivered digest (%d feeds, %d total items)",
            sum(1 for v in new_by_feed.values() if v),
            sum(len(v) for v in new_by_feed.values()),
        )


# ---------------------------------------------------------------------------
# Feed fetching & parsing
# ---------------------------------------------------------------------------
async def _fetch_feed(url: str) -> list[FeedItem]:
    """Fetch and parse a single RSS / Atom feed."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("briefings: fetch %s failed: %r", url, exc)
        return []
    try:
        return _parse(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("briefings: parse %s failed: %r", url, exc)
        return []


def _parse(xml_text: str) -> list[FeedItem]:
    """Parse an RSS or Atom feed from raw XML.

    Pure stdlib so we don't need feedparser. Supports a generous subset:
    RSS 2.0 (``<rss><channel><item>``) and Atom (``<feed><entry>``).
    """
    root = ET.fromstring(xml_text)
    items: list[FeedItem] = []

    if root.tag.endswith("rss") or root.tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            for it in channel.findall("item"):
                ts = _parse_date(it.findtext("pubDate"))
                items.append(
                    FeedItem(
                        title=(it.findtext("title") or "").strip() or "(untitled)",
                        link=(it.findtext("link") or "").strip(),
                        published_ts=ts,
                        summary=_strip((it.findtext("description") or "")).strip()[:240],
                    )
                )
    elif root.tag.endswith("feed") or root.tag == "feed":
        ns = ""
        # Atom feeds often use a namespace on the root element.
        if "}" in root.tag:
            ns = "{" + root.tag.split("}", 1)[0][1:] + "}"
        for it in root.findall(f"{ns}entry"):
            ts = _parse_date(it.findtext(f"{ns}updated") or it.findtext(f"{ns}published"))
            link_el = it.find(f"{ns}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary_el = it.find(f"{ns}summary")
            if summary_el is None:
                summary_el = it.find(f"{ns}content")
            summary = _strip(summary_el.text or "") if summary_el is not None else ""
            items.append(
                FeedItem(
                    title=_strip(it.findtext(f"{ns}title") or "").strip() or "(untitled)",
                    link=link,
                    published_ts=ts,
                    summary=summary.strip()[:240],
                )
            )
    return items


def _parse_date(raw: Optional[str]) -> float:
    if not raw:
        return 0.0
    raw = raw.strip()
    # RFC 822 (pubDate)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    # ISO 8601
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _strip(text: str) -> str:
    """Crude HTML stripper (avoid pulling in BeautifulSoup for one line)."""
    out: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Config / state / digest
# ---------------------------------------------------------------------------
def _configured_feeds(settings: Settings) -> str:
    return (settings.briefing_feeds or "").strip()


def _parse_feeds(spec: str) -> list[str]:
    out: list[str] = []
    for raw in spec.split(","):
        url = raw.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            logger.debug("briefings: skipping non-http feed %r", url)
            continue
        out.append(url)
    return out


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True))
    except Exception:
        logger.exception("briefings: failed to persist state to %s", path)


def _render_digest(items_by_feed: dict[str, list[FeedItem]]) -> str:
    """Build a readable digest for one or more feeds."""
    lines: list[str] = []
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"OpenPup briefing ({today})")
    lines.append("")
    for url, items in sorted(items_by_feed.items()):
        if not items:
            continue
        host = _host_label(url)
        lines.append(f"== {host} ({len(items)} new) ==")
        for it in items[:8]:  # cap per-feed
            if it.link:
                lines.append(f"- {it.title}")
                lines.append(f"  {it.link}")
            else:
                lines.append(f"- {it.title}")
        if len(items) > 8:
            lines.append(f"  ... and {len(items) - 8} more")
        lines.append("")
    lines.append(f"Sources: {len(items_by_feed)} | Generated by OpenPup")
    return "\n".join(lines).rstrip() + "\n"


def _host_label(url: str) -> str:
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        host = (p.netloc or "").replace("www.", "")
        return host or url
    except Exception:
        return url


def _in_quiet_hours(settings: Settings, now_ts: float) -> bool:
    """True if the current local time is inside the configured quiet hours."""
    qh = (settings.quiet_hours or "").strip()
    if not qh:
        return False
    try:
        start, end = qh.split("-", 1)
        # Accept "22-7" or "22:00-07:00" or "22:00-7". Parse HH:MM in each side.
        sh, sm = _parse_clock(start.strip())
        eh, em = _parse_clock(end.strip())
    except Exception:
        return False
    now = datetime.fromtimestamp(now_ts)
    minutes = now.hour * 60 + now.minute
    s = sh * 60 + sm
    e = eh * 60 + em
    if s <= e:
        return s <= minutes < e
    # Wraps midnight (e.g. 22:00-07:00)
    return minutes >= s or minutes < e


def _parse_clock(spec: str) -> tuple[int, int]:
    """Parse 'HH' or 'HH:MM' into (hour, minute)."""
    if ":" in spec:
        h, m = spec.split(":", 1)
    else:
        h, m = spec, "0"
    return int(h), int(m)
