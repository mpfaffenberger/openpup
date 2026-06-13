"""Owner approval gate (openpup.security.approval).

Drives request_approval through the real runtime inbound path (StubHost +
fresh registry, same pattern as test_session_recording): the owner's
"yes <id>" / "no <id>" replies must resolve the pending future and be
consumed WITHOUT agent routing; non-owner replies must never resolve.
"""

from __future__ import annotations

import asyncio
import os
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openpup import memory
from openpup import runtime as runtime_mod
from openpup import sessions as sessions_mod
from openpup.access import AccessControl
from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.runtime import OpenPup
from openpup.security import approval
from openpup.security.approval import request_approval
from openpup.sessions import SessionStore

OWNER_ADDRESS = "telegram:777"

# Mask owner vars load_dotenv may have injected from a real .env file.
_OWNER_KEYS = ("OPENPUP_OWNER_ADDRESS", "OPENPUP_OWNER_ADDRESSES")


def _settings(**kw) -> Settings:
    clean_env = {k: v for k, v in os.environ.items() if k not in _OWNER_KEYS}
    with patch.dict(os.environ, clean_env, clear=True):
        return Settings(_env_file=None, **kw)


class StubHost:
    """Drop-in agent host: returns a canned reply, remembers prompts."""

    def __init__(self, reply: str = "woof, noted!") -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def run(self, prompt, conversation="default", model=None, keep_history=True):
        self.prompts.append(prompt)
        return self.reply

    def has_history(self, conversation: str) -> bool:
        return True  # skip transcript rehydration -- not what these tests cover

    def reset_conversation(self, conversation: str) -> None:
        pass


class CaptureAdapter:
    """Fake telegram adapter: records outbound envelopes."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


@pytest.fixture
def store(tmp_path, monkeypatch) -> SessionStore:
    s = SessionStore(path=tmp_path / "sessions.db")
    monkeypatch.setattr(sessions_mod, "_store", s)
    return s


@pytest.fixture
def adapter() -> CaptureAdapter:
    return CaptureAdapter()


@pytest.fixture
def pup(tmp_path, monkeypatch, store, adapter) -> OpenPup:
    """An OpenPup whose registry + settings are also approval's singletons."""
    settings = _settings(OPENPUP_OWNER_ADDRESS=OWNER_ADDRESS)
    pup = OpenPup(settings=settings)
    pup.host = StubHost()
    pup.registry = PlatformRegistry()
    pup.registry.register(adapter)
    pup.access = AccessControl(tmp_path / "access.json", owner_address=OWNER_ADDRESS)
    # approval.request_approval reads the process singletons — point them here.
    monkeypatch.setattr("openpup.config.get_settings", lambda: settings)
    monkeypatch.setattr("openpup.messaging.registry.get_registry", lambda: pup.registry)
    # Keep tests off the real contact directory + kennel memory.
    monkeypatch.setattr(
        runtime_mod, "get_directory", lambda: SimpleNamespace(record=lambda *a: None)
    )
    monkeypatch.setattr(memory, "remember_about_contact", lambda *a, **k: True)
    monkeypatch.setattr(memory, "recent_about_contact", lambda *a, **k: [])
    monkeypatch.setattr(approval, "_PENDING", {})
    return pup


async def _sent_approval_id(adapter: CaptureAdapter) -> str:
    """Wait for the approval message to land and pull the id out of it."""
    for _ in range(50):
        if adapter.sent:
            break
        await asyncio.sleep(0)
    match = re.search(r"yes ([0-9a-f]{6})", adapter.sent[0].text)
    assert match, f"no approval id in {adapter.sent[0].text!r}"
    return match.group(1)


def _owner_reply(text: str) -> Envelope:
    return Envelope(platform="telegram", channel="777", sender="Mike", text=text)


# ---------------------------------------------------------------------------
# Happy path / denial / timeout
# ---------------------------------------------------------------------------
async def test_owner_yes_approves(pup, adapter):
    task = asyncio.create_task(request_approval("delete the prod database", timeout_s=5))
    approval_id = await _sent_approval_id(adapter)
    assert "[approval] delete the prod database" in adapter.sent[0].text
    assert adapter.sent[0].address == OWNER_ADDRESS

    await pup.handle_inbound(_owner_reply(f"yes {approval_id}"))

    assert await task is True
    # Consumed: no agent invocation, short confirmation went back.
    assert pup.host.prompts == []
    assert any("Approved" in e.text for e in adapter.sent[1:])


async def test_owner_no_denies(pup, adapter):
    task = asyncio.create_task(request_approval("wipe the kennel", timeout_s=5))
    approval_id = await _sent_approval_id(adapter)

    await pup.handle_inbound(_owner_reply(f"no {approval_id}"))

    assert await task is False
    assert pup.host.prompts == []
    assert any("Denied" in e.text for e in adapter.sent[1:])


async def test_timeout_denies_by_default(pup, adapter):
    assert await request_approval("slow owner", timeout_s=0) is False
    assert approval.pending_count() == 0  # cleaned up


# ---------------------------------------------------------------------------
# Trust boundary: non-owner replies never resolve
# ---------------------------------------------------------------------------
async def test_non_owner_reply_never_resolves(pup, adapter):
    task = asyncio.create_task(request_approval("send money", timeout_s=5))
    approval_id = await _sent_approval_id(adapter)

    stranger = Envelope(
        platform="telegram", channel="999", sender="Mallory", text=f"yes {approval_id}"
    )
    await pup.handle_inbound(stranger)

    # Routed to the agent like any normal message; approval still pending.
    assert pup.host.prompts, "non-owner message should reach the agent"
    assert not task.done()
    assert approval.pending_count() == 1

    await pup.handle_inbound(_owner_reply(f"no {approval_id}"))
    assert await task is False


async def test_owner_reply_with_unknown_id_routes_to_agent(pup, adapter):
    await pup.handle_inbound(_owner_reply("yes abc123"))
    assert pup.host.prompts, "unknown-id replies fall through to normal routing"


# ---------------------------------------------------------------------------
# Default-deny on missing owner / delivery failure
# ---------------------------------------------------------------------------
async def test_no_owner_configured_denies(pup, adapter, monkeypatch):
    monkeypatch.setattr("openpup.config.get_settings", lambda: _settings())
    assert await request_approval("anything", timeout_s=5) is False
    assert adapter.sent == []


async def test_delivery_failure_denies(pup, monkeypatch):
    empty = PlatformRegistry()  # no adapters -> send() returns False
    monkeypatch.setattr("openpup.messaging.registry.get_registry", lambda: empty)
    assert await request_approval("anything", timeout_s=5) is False
    assert approval.pending_count() == 0
