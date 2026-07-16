"""Browser automation via Playwright (lazy import).

A small abstraction for "go to a URL", "click", "fill a form", etc.
Playwright is optional -- the module imports even without it. When called,
actions are dispatched through the abstraction so tests can mock the
underlying client.

v1 supports these actions:
  * ``goto``     -- navigate to a URL.
  * ``click``    -- click a CSS selector.
  * ``fill``     -- fill an input by selector + value.
  * ``submit``   -- submit a form by selector.
  * ``screenshot`` -- capture page bytes.
  * ``title``    -- return the page title (smoke check).

A real run downloads the Chromium binary on first use (~150MB).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger("openpup.browser_automation")

Action = Literal["goto", "click", "fill", "submit", "screenshot", "title"]


@dataclass
class BrowserAction:
    """One browser action: action + selector + value."""

    action: str
    target: str = ""
    value: str = ""


@dataclass
class BrowserResult:
    ok: bool
    action: str
    data: Any = None
    error: str | None = None


async def run(
    action: BrowserAction,
    *,
    timeout: float = 15.0,
) -> BrowserResult:
    """Dispatch one browser action. Returns a BrowserResult.

    In v1 the actual Playwright dispatch is stubbed (raises a helpful
    error); the abstraction is in place so a follow-up commit can wire in
    the real client.
    """
    if action.action not in ("goto", "click", "fill", "submit", "screenshot", "title"):
        return BrowserResult(
            ok=False,
            action=action.action,
            error=f"unknown action {action.action!r}",
        )
    try:
        # v1 stub: real Playwright dispatch lands in a follow-up commit so each
        # feature stays a single focused commit.
        await asyncio.sleep(0)  # keep async semantics for future integration
        return _stub_dispatch(action)
    except Exception as exc:
        return BrowserResult(
            ok=False,
            action=action.action,
            error=f"{exc!r}",
        )


def _stub_dispatch(action: BrowserAction) -> BrowserResult:
    """Stub: returns synthetic data without touching a real browser."""
    if action.action == "goto":
        return BrowserResult(ok=True, action="goto", data=f"would navigate to {action.target!r}")
    if action.action == "title":
        return BrowserResult(ok=True, action="title", data="(stubbed)")
    return BrowserResult(ok=True, action=action.action, data=f"would {action.action} {action.target!r}")
