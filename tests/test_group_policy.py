"""Tests for the group-policy module.

Covers the per-platform GroupPolicy dataclass, the JSON store round-trip,
and the should_reply() decision logic across modes / mentions / keywords.
"""

import json
from pathlib import Path

import pytest

from openpup.group_policy import (
    GroupDecision,
    GroupPolicy,
    GroupPolicyStore,
    MODES,
    MODE_OPEN,
    MODE_SILENT,
    MODE_SMART,
    get_store,
    should_reply,
)
from openpup.messaging.envelope import Envelope


# ---------------------------------------------------------------------------
# Dataclass round-trip
# ---------------------------------------------------------------------------
class TestGroupPolicy:
    def test_defaults(self):
        p = GroupPolicy(platform="telegram")
        assert p.mode == MODE_SMART
        assert p.require_mention is True
        assert p.require_keyword == ""

    def test_to_from_roundtrip(self):
        p = GroupPolicy(
            platform="discord",
            mode=MODE_OPEN,
            require_mention=False,
            require_keyword="hey pup",
            bot_user_ids=["123"],
        )
        raw = p.to_dict()
        restored = GroupPolicy.from_dict(raw)
        assert restored.platform == "discord"
        assert restored.mode == MODE_OPEN
        assert restored.require_mention is False
        assert restored.require_keyword == "hey pup"
        assert restored.bot_user_ids == ["123"]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class TestGroupPolicyStore:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "policies.json"
        s = GroupPolicyStore(path)
        s.upsert(GroupPolicy(platform="telegram", mode=MODE_OPEN))
        s.upsert(GroupPolicy(platform="discord", mode=MODE_SILENT, require_mention=False))

        s2 = GroupPolicyStore(path)
        all_pol = s2.load()
        assert len(all_pol) == 2
        assert all_pol["telegram"].mode == MODE_OPEN
        assert all_pol["discord"].mode == MODE_SILENT
        assert all_pol["discord"].require_mention is False

    def test_get_with_default(self, tmp_path):
        s = GroupPolicyStore(tmp_path / "x.json")
        p = s.get("telegram")
        assert p.platform == "telegram"
        assert p.mode == MODE_SMART

    def test_remove(self, tmp_path):
        s = GroupPolicyStore(tmp_path / "x.json")
        s.upsert(GroupPolicy(platform="telegram"))
        assert s.remove("telegram") is True
        # Removing again returns False.
        assert s.remove("telegram") is False

    def test_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "policies.json"
        path.write_text("not json")
        s = GroupPolicyStore(path)
        assert s.load() == {}


# ---------------------------------------------------------------------------
# should_reply decision logic
# ---------------------------------------------------------------------------
class TestShouldReply:
    def test_dm_always_allowed(self):
        env = Envelope(platform="telegram", channel="123", chat_type="dm", text="hi")
        pol = GroupPolicy(platform="telegram", mode=MODE_SILENT)
        d = should_reply(env, pol)
        assert d.allowed is True
        assert "dm" in d.reason.lower()

    def test_group_silent_mode_never_replies(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="@bot hi")
        pol = GroupPolicy(platform="telegram", mode=MODE_SILENT)
        d = should_reply(env, pol)
        assert d.allowed is False
        assert "silent" in d.reason.lower()

    def test_group_open_mode_always_replies(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="ambient chatter")
        pol = GroupPolicy(platform="telegram", mode=MODE_OPEN)
        d = should_reply(env, pol)
        assert d.allowed is True

    def test_smart_no_mention_blocks_when_required(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="hi everyone")
        pol = GroupPolicy(platform="telegram", mode=MODE_SMART, require_mention=True)
        d = should_reply(env, pol)
        assert d.allowed is False
        assert "mention" in d.reason.lower()

    def test_smart_with_explicit_mention_allows(self):
        env = Envelope(
            platform="telegram",
            channel="g",
            chat_type="group",
            text="@bot please help",
            mentions=["bot_id"],
        )
        pol = GroupPolicy(platform="telegram", mode=MODE_SMART, require_mention=True)
        d = should_reply(env, pol, bot_user_id="bot_id")
        assert d.allowed is True
        assert "mention" in d.reason.lower() or "explicit" in d.reason.lower()

    def test_smart_with_keyword_in_text_allows(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="hey pup!")
        pol = GroupPolicy(
            platform="telegram",
            mode=MODE_SMART,
            require_mention=True,
            require_keyword="pup",
        )
        d = should_reply(env, pol)
        assert d.allowed is True
        assert "keyword" in d.reason.lower()

    def test_smart_keyword_case_insensitive(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="Hey PUP!")
        pol = GroupPolicy(
            platform="telegram",
            mode=MODE_SMART,
            require_keyword="pup",
        )
        d = should_reply(env, pol)
        assert d.allowed is True

    def test_no_require_mention_no_keyword_always_allows(self):
        env = Envelope(platform="telegram", channel="g", chat_type="group", text="ambient")
        pol = GroupPolicy(
            platform="telegram",
            mode=MODE_SMART,
            require_mention=False,
            require_keyword="",
        )
        d = should_reply(env, pol)
        assert d.allowed is True

    def test_bot_user_id_in_mentions_allows(self):
        env = Envelope(
            platform="telegram",
            channel="g",
            chat_type="group",
            text="@somebody",
            mentions=["bot_id"],
        )
        pol = GroupPolicy(platform="telegram", mode=MODE_SMART, require_mention=True)
        d = should_reply(env, pol, bot_user_id="bot_id")
        assert d.allowed is True
