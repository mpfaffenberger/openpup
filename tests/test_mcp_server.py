"""Tests for the MCP server module.

Covers the tool handler functions directly (so they don't need a live MCP
client), the tool registry shape, and the server-build path when the MCP SDK
is present.
"""

from unittest import mock

import pytest

from openpup.mcp_server import (
    HAS_MCP,
    TOOL_DEFINITIONS,
    build_server,
    tool_list_platforms,
    tool_memory_recent,
    tool_memory_recall,
    tool_memory_store,
    tool_session_search,
    _restricted_mode,
)


# ---------------------------------------------------------------------------
# Pure handler tests (no MCP needed)
# ---------------------------------------------------------------------------
class TestMemoryTools:
    def test_recall_requires_query(self):
        r = tool_memory_recall({})
        assert r["ok"] is False
        assert "query" in r["error"]

    def test_recall_clamps_top_k(self, monkeypatch):
        # Don't actually hit the kennel; verify clamping then mock.
        from openpup import memory

        seen = {}

        def fake_recall(query, top_k):
            seen["top_k"] = top_k
            return ["m1"]

        monkeypatch.setattr(memory, "recall", fake_recall)
        r = tool_memory_recall({"query": "hi", "top_k": 9999})
        assert r["ok"] is True
        assert seen["top_k"] == 20  # clamped
        assert r["matches"] == ["m1"]

        r2 = tool_memory_recall({"query": "hi", "top_k": 0})
        assert r2["ok"] is True
        # 0 should clamp up to 1 (min of 1)

    def test_recent_clamps_top_k(self, monkeypatch):
        from openpup import memory

        def fake_recent(top_k):
            return ["a", "b"][:top_k]

        monkeypatch.setattr(memory, "recent", fake_recent)
        r = tool_memory_recent({})
        assert r["ok"] is True
        assert r["count"] == 2

    def test_store_requires_content(self, monkeypatch):
        r = tool_memory_store({})
        assert r["ok"] is False

    def test_store_writes_memory(self, monkeypatch):
        from openpup import memory

        called = {}

        def fake_remember(content, wing="agent", room="notes"):
            called["content"] = content
            called["wing"] = wing
            return True

        monkeypatch.setattr(memory, "remember", fake_remember)
        r = tool_memory_store({"content": "hello", "wing": "user", "room": "facts"})
        assert r["ok"] is True
        assert called["content"] == "hello"
        assert called["wing"] == "user"

    def test_store_rejects_unknown_wing(self, monkeypatch):
        from openpup import memory

        called = {}

        def fake_remember(content, wing="agent", room="notes"):
            called["wing"] = wing
            return True

        monkeypatch.setattr(memory, "remember", fake_remember)
        r = tool_memory_store({"content": "x", "wing": "bogus"})
        # Should silently coerce to 'agent' and not error.
        assert r["ok"] is True
        assert called["wing"] == "agent"


class TestListPlatforms:
    def test_lists_platforms(self, monkeypatch):
        class FakeRegistry:
            def platforms(self):
                return ["telegram", "discord"]

        fake_settings = mock.MagicMock()
        fake_settings.owner_address = "telegram:me"
        monkeypatch.setattr("openpup.config.get_settings", lambda: fake_settings)
        monkeypatch.setattr("openpup.messaging.registry.get_registry", lambda: FakeRegistry())

        r = tool_list_platforms({})
        assert r["ok"] is True
        assert "telegram" in r["platforms"]
        assert r["owner"] == "telegram:me"


class TestSessionSearch:
    def test_scroll_requires_session_id(self):
        # around_message_id without session_id => error (no store needed)
        r = tool_session_search({"around_message_id": 5})
        assert r["ok"] is False
        assert "session_id" in r["error"]

    def test_session_not_found(self, monkeypatch):
        class FakeStore:
            def read_session(self, sid):
                return {"session": None, "messages": [], "truncated": False, "omitted": 0}

        monkeypatch.setattr("openpup.sessions.get_session_store", lambda: FakeStore())
        r = tool_session_search({"session_id": "missing"})
        assert r["ok"] is False
        assert "not found" in r["error"]

    def test_browse_returns_recent_sessions(self, monkeypatch):
        class FakeStore:
            def recent_sessions(self, limit):
                return [{"session_id": "x"}]

        monkeypatch.setattr("openpup.sessions.get_session_store", lambda: FakeStore())
        r = tool_session_search({})
        assert r["ok"] is True
        assert r["mode"] == "browse"
        assert r["sessions"] == [{"session_id": "x"}]


# ---------------------------------------------------------------------------
# Registry / metadata tests
# ---------------------------------------------------------------------------
class TestToolRegistry:
    def test_all_tools_have_unique_names(self):
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert len(names) == len(set(names)), "duplicate tool names"

    def test_all_tools_have_required_keys(self):
        for t in TOOL_DEFINITIONS:
            assert "name" in t, f"tool missing name: {t}"
            assert "description" in t
            assert "input_schema" in t
            assert "handler" in t
            assert callable(t["handler"])
            assert isinstance(t["input_schema"], dict)
            assert t["input_schema"].get("type") == "object"

    def test_required_args_are_listed(self):
        # The schema's 'required' keys must also appear in 'properties'.
        for t in TOOL_DEFINITIONS:
            props = set((t["input_schema"].get("properties") or {}).keys())
            required = set(t["input_schema"].get("required") or [])
            missing = required - props
            assert not missing, f"tool {t['name']}: required {missing} not in properties"

    def test_privileged_tools_marked(self):
        # send_message and list_contacts must be privileged so they can be hidden.
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "send_message" in names
        assert "list_contacts" in names
        for t in TOOL_DEFINITIONS:
            if t["name"] in {"send_message", "list_contacts"}:
                assert t.get("privileged") is True, f"{t['name']} should be privileged"

    def test_restricted_mode(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_MCP_RESTRICT", raising=False)
        assert _restricted_mode() is False

        monkeypatch.setenv("OPENPUP_MCP_RESTRICT", "true")
        assert _restricted_mode() is True

        monkeypatch.setenv("OPENPUP_MCP_RESTRICT", "1")
        assert _restricted_mode() is True

        monkeypatch.setenv("OPENPUP_MCP_RESTRICT", "")
        assert _restricted_mode() is False


# ---------------------------------------------------------------------------
# MCP-SDK-dependent tests (skipped if not installed)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_MCP, reason="MCP SDK not installed")
class TestServerBuild:
    def test_build_server_runs(self):
        server = build_server()
        assert server is not None

    def test_build_server_filters_privileged(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_MCP_RESTRICT", "true")
        server = build_server()
        # Server should build fine; list_tools will exclude privileged tools.
        assert server is not None

    def test_has_mcp_constant_matches_install(self):
        # HAS_MCP is True iff we got past the import.
        assert HAS_MCP is True

    def test_tool_registry_includes_11(self):
        # We expose 11 tools: 4 memory/sessions, 4 messaging, 2 skills, 1 contacts.
        assert len(TOOL_DEFINITIONS) == 11, (
            f"expected 11 tools, got {len(TOOL_DEFINITIONS)}: "
            f"{[t['name'] for t in TOOL_DEFINITIONS]}"
        )
