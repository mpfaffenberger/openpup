"""Tests for the browser_automation module."""

import asyncio

import pytest

from openpup.browser_automation import BrowserAction, BrowserResult, run


class TestDispatch:
    def test_goto(self):
        async def go():
            return await run(BrowserAction(action="goto", target="https://example.com"))

        r = asyncio.run(go())
        assert r.ok
        assert "https://example.com" in str(r.data)

    def test_click(self):
        async def go():
            return await run(BrowserAction(action="click", target="#login"))

        r = asyncio.run(go())
        assert r.ok
        assert "#login" in str(r.data)

    def test_fill(self):
        async def go():
            return await run(BrowserAction(action="fill", target="#email", value="alice@example.com"))

        r = asyncio.run(go())
        assert r.ok
        assert "fill" in str(r.data)

    def test_unknown_action(self):
        async def go():
            return await run(BrowserAction(action="bogus"))

        r = asyncio.run(go())
        assert not r.ok
        assert "unknown action" in r.error

    def test_title(self):
        async def go():
            return await run(BrowserAction(action="title"))

        r = asyncio.run(go())
        assert r.ok
        assert r.data == "(stubbed)"

    def test_submit(self):
        async def go():
            return await run(BrowserAction(action="submit", target="form"))

        r = asyncio.run(go())
        assert r.ok
        assert "submit" in str(r.data)

    def test_screenshot(self):
        async def go():
            return await run(BrowserAction(action="screenshot"))

        r = asyncio.run(go())
        assert r.ok
