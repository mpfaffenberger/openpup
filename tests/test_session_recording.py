"""Transcript recording: every conversation turn lands in the SessionStore.

Routes envelopes through the real runtime (stubbed agent host + fresh registry)
and runs heartbeat behaviors directly, asserting user/assistant rows show up in
a tmp-path SessionStore under the date-bucketed session id convention:

* conversations: ``{platform}:{channel}:{YYYYMMDD}``
* heartbeat:     ``heartbeat:{behavior}:{YYYYMMDD}``
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from openpup import memory
from openpup import runtime as runtime_mod
from openpup import sessions as sessions_mod
from openpup.access import AccessControl
from openpup.config import Settings
from openpup.messaging.envelope import Envelope
from openpup.messaging.registry import PlatformRegistry
from openpup.runtime import OpenPup
from openpup.sessions import SessionStore


def today() -> str:
    return time.strftime("%Y%m%d")


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


@pytest.fixture
def store(tmp_path, monkeypatch) -> SessionStore:
    """A tmp-path store installed as the process singleton."""
    s = SessionStore(path=tmp_path / "sessions.db")
    monkeypatch.setattr(sessions_mod, "_store", s)
    return s


@pytest.fixture
def pup(tmp_path, monkeypatch) -> OpenPup:
    """An OpenPup wired to a stub host, fresh registry and tmp access policy."""
    pup = OpenPup(settings=Settings(_env_file=None))
    pup.host = StubHost()
    pup.registry = PlatformRegistry()  # no adapters; send() just returns False
    pup.access = AccessControl(tmp_path / "access.json")
    # Keep the test off the real contact directory + kennel memory.
    monkeypatch.setattr(
        runtime_mod, "get_directory", lambda: SimpleNamespace(record=lambda *a: None)
    )
    monkeypatch.setattr(memory, "remember_about_contact", lambda *a, **k: True)
    monkeypatch.setattr(memory, "recent_about_contact", lambda *a, **k: [])
    return pup


async def test_inbound_turn_recorded(pup, store):
    env = Envelope(platform="telegram", channel="777", sender="alice", text="hello pup")
    await pup.handle_inbound(env)

    session_id = f"telegram:777:{today()}"
    dump = store.read_session(session_id)
    assert dump["session"]["source"] == "telegram:777"
    assert [(m["role"], m["content"]) for m in dump["messages"]] == [
        ("user", "hello pup"),
        ("assistant", "woof, noted!"),
    ]


async def test_turns_accumulate_in_same_daily_session(pup, store):
    env = Envelope(platform="discord", channel="42", text="first")
    await pup.handle_inbound(env)
    await pup.handle_inbound(env.model_copy(update={"text": "second"}))

    dump = store.read_session(f"discord:42:{today()}")
    assert [m["content"] for m in dump["messages"]] == [
        "first",
        "woof, noted!",
        "second",
        "woof, noted!",
    ]


async def test_blocked_message_not_recorded(pup, store):
    pup.access.set_mode("telegram", "owner_only")
    await pup.handle_inbound(Envelope(platform="telegram", channel="666", text="let me in"))

    assert store.recent_sessions() == []


async def test_broken_store_never_breaks_message_flow(pup, store, monkeypatch):
    def boom():
        raise RuntimeError("transcripts are on fire")

    monkeypatch.setattr(sessions_mod, "get_session_store", boom)
    # Must not raise — the reply path matters more than bookkeeping.
    await pup.handle_inbound(Envelope(platform="telegram", channel="777", text="hi"))
    assert pup.host.prompts  # the agent still ran


async def test_reflect_records_heartbeat_session(store, monkeypatch):
    from openpup.heartbeat import reflect as reflect_mod

    monkeypatch.setattr(memory, "recent", lambda top_k=5: [])
    monkeypatch.setattr(memory, "remember", lambda *a, **k: True)
    host = StubHost(reply="A quiet day; follow up on the trip plans.")

    text = await reflect_mod.reflect(host, Settings(_env_file=None))

    assert text == "A quiet day; follow up on the trip plans."
    dump = store.read_session(f"heartbeat:reflect:{today()}")
    assert dump["session"]["source"] == "heartbeat"
    assert [(m["role"], m["content"]) for m in dump["messages"]] == [("assistant", text)]


async def test_reflect_prompt_includes_learning_loop_nudges(store, monkeypatch):
    from openpup.heartbeat import reflect as reflect_mod

    monkeypatch.setattr(memory, "recent", lambda top_k=5: [])
    remembered: list[str] = []
    monkeypatch.setattr(memory, "remember", lambda content, **k: remembered.append(content))
    host = StubHost(reply="Skill candidate: deploy-dance — keeps coming up.")

    text = await reflect_mod.reflect(host, Settings(_env_file=None))

    sent = host.prompts[0]
    # tools are available in the reflection turn — say so and use them
    assert "Your tools are available" in sent
    assert "durable fact about your human" in sent
    assert "USER wing" in sent
    # skill promotion is suggestion-only (owner trust boundary)
    assert "do NOT create a skill" in sent
    assert "Skill candidate:" in sent
    # reflection still lands in agent memory as before
    assert remembered == [f"[reflection] {text}"]


async def test_routine_prompt_job_records_both_turns(store):
    from openpup.heartbeat import routines as routines_mod

    job = SimpleNamespace(name="brief", message=None, prompt="summarize the day", deliver=None)
    scheduler = SimpleNamespace(due=lambda: [job])
    host = StubHost(reply="the daily summary")

    fired = await routines_mod.run_due_routines(
        host, Settings(_env_file=None), PlatformRegistry(), scheduler
    )

    assert fired == ["brief"]
    dump = store.read_session(f"heartbeat:routines:{today()}")
    assert [(m["role"], m["content"]) for m in dump["messages"]] == [
        ("user", "summarize the day"),
        ("assistant", "the daily summary"),
    ]
