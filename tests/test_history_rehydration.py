"""The pup must see prior conversation turns per channel -- not just memory.

Live in-memory history (AgentHost._histories) carries a running session, but
it's wiped on restart. These tests cover the persistent fallback: recent
transcript turns are rehydrated into the prompt when (and only when) there's
no live history for that peer.
"""

from types import SimpleNamespace

from openpup import access
from openpup.agent_host import AgentHost
from openpup.messaging.envelope import Envelope
from openpup.runtime import OpenPup
from openpup.sessions import SessionStore


# ---- SessionStore.recent_for_source --------------------------------------
def _store(tmp_path):
    return SessionStore(tmp_path / "s.db")


def test_recent_for_source_chronological_across_buckets(tmp_path):
    store = _store(tmp_path)
    addr = "telegram:7"
    store.append(f"{addr}:20260612", addr, "user", "first")
    store.append(f"{addr}:20260612", addr, "assistant", "second")
    store.append(f"{addr}:20260613", addr, "user", "third")
    rows = store.recent_for_source(addr, limit=10)
    assert [r["content"] for r in rows] == ["first", "second", "third"]


def test_recent_for_source_isolates_peers(tmp_path):
    store = _store(tmp_path)
    store.append("telegram:7:20260613", "telegram:7", "user", "mine")
    store.append("telegram:9:20260613", "telegram:9", "user", "theirs")
    rows = store.recent_for_source("telegram:7")
    assert [r["content"] for r in rows] == ["mine"]


def test_recent_for_source_limit_keeps_newest(tmp_path):
    store = _store(tmp_path)
    addr = "sms:+1"
    for i in range(5):
        store.append(f"{addr}:20260613", addr, "user", f"m{i}")
    rows = store.recent_for_source(addr, limit=2)
    assert [r["content"] for r in rows] == ["m3", "m4"]  # newest two, chronological


def test_recent_for_source_empty_for_unknown(tmp_path):
    assert _store(tmp_path).recent_for_source("telegram:nobody") == []


# ---- AgentHost.has_history -----------------------------------------------
def test_has_history_tracks_live_conversations():
    host = AgentHost()
    assert host.has_history("telegram:7") is False
    host._histories["telegram:7"] = ["a turn"]
    assert host.has_history("telegram:7") is True
    host._histories["telegram:7"] = []  # empty list is still "no history"
    assert host.has_history("telegram:7") is False


# ---- runtime rehydration gating ------------------------------------------
def test_recent_conversation_lines_formats_turns(tmp_path, monkeypatch):
    store = _store(tmp_path)
    addr = "telegram:7"
    store.append(f"{addr}:20260613", addr, "user", "watch my email")
    store.append(f"{addr}:20260613", addr, "assistant", "on it")
    monkeypatch.setattr(
        "openpup.sessions.get_session_store", lambda: store, raising=True
    )
    lines = OpenPup._recent_conversation_lines(object(), addr, "Mike")
    assert lines[0].startswith("Recent conversation with Mike")
    assert "- Mike: watch my email" in lines
    assert "- You: on it" in lines


def test_context_prefix_injects_only_without_live_history(tmp_path, monkeypatch):
    store = _store(tmp_path)
    addr = "telegram:7"
    store.append(f"{addr}:20260613", addr, "user", "earlier message")
    monkeypatch.setattr("openpup.sessions.get_session_store", lambda: store, raising=True)
    monkeypatch.setattr("openpup.memory.recent_about_contact", lambda *a, **k: [])
    env = Envelope(platform="telegram", channel="7", sender="Mike", text="now")

    # No live history (post-restart): prior turns are rehydrated.
    me = SimpleNamespace(
        host=SimpleNamespace(has_history=lambda _a: False),
        settings=SimpleNamespace(threat_guard=False),
        _recent_conversation_lines=OpenPup._recent_conversation_lines.__get__(
            SimpleNamespace()
        ),
    )
    out = OpenPup._context_prefix(me, env, access.OWNER)
    assert "earlier message" in out

    # Live history present: skip rehydration (the agent already has the thread).
    me.host = SimpleNamespace(has_history=lambda _a: True)
    out2 = OpenPup._context_prefix(me, env, access.OWNER)
    assert "earlier message" not in out2
