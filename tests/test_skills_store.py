"""SkillStore + loader: agentskills.io skill folders, lifecycle, prompt index."""

import logging
import os
import time

import pytest

from openpup.skills import loader as loader_mod
from openpup.skills import store as store_mod
from openpup.skills.store import SkillStore, parse_frontmatter, render_frontmatter

DESC = "Does a thing well. Use when testing skills."


@pytest.fixture
def root(tmp_path):
    return tmp_path / "skills"


@pytest.fixture
def store(root):
    return SkillStore(root=root)


def _write_skill(
    root, name, description=DESC, body="# How\nInstructions.", folder=None, fm_extra=""
):
    """Hand-write a skill folder (simulating a user-installed skill)."""
    skill_dir = root / (folder or name)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{fm_extra}---\n\n{body}\n"
    )
    return skill_dir


# ---- frontmatter -----------------------------------------------------------
def test_frontmatter_round_trip():
    fm = {
        "name": "pdf-processing",
        "description": "Extracts text from PDFs. Use when handling PDF files.",
        "license": "MIT",
        "compatibility": "Requires Python 3.10+",
        "metadata": {"version": "1.0.0", "created_by": "openpup", "state": "active"},
        "allowed-tools": ["bash", "read_file"],
    }
    parsed, body = parse_frontmatter(render_frontmatter(fm) + "\n\nThe body.\n")
    assert parsed == fm
    assert body.strip() == "The body."


def test_frontmatter_folded_description_and_no_frontmatter():
    text = "---\nname: pdf\ndescription: Extracts text.\n  Use when asked nicely.\n---\nBody"
    fm, body = parse_frontmatter(text)
    assert fm["description"] == "Extracts text. Use when asked nicely."
    assert body == "Body"
    assert parse_frontmatter("just markdown") == ({}, "just markdown")


# ---- validation ------------------------------------------------------------
def test_discovery_skips_invalid_skills(store, root, caplog):
    _write_skill(root, "Bad_Name")  # uppercase/underscore
    _write_skill(root, "x" * 65, folder="too-long")  # name too long (+ mismatch)
    _write_skill(root, "no-desc", description="")  # missing description
    _write_skill(root, "mismatch", folder="other-folder")  # name != folder
    _write_skill(root, "good-skill")
    with caplog.at_level(logging.WARNING, logger="openpup.skills"):
        skills = store.discover()
    assert [s.name for s in skills] == ["good-skill"]
    assert sum("skipping" in r.message for r in caplog.records) == 4


def test_discover_on_missing_root_is_empty(tmp_path):
    assert SkillStore(root=tmp_path / "nope").discover() == []


# ---- create / discover / get ------------------------------------------------
def test_create_discover_get_cycle(store):
    skill = store.create("test-skill", DESC, body="# Steps\nDo the thing.")
    assert skill.name == "test-skill"
    assert (store.root / "test-skill" / "SKILL.md").exists()
    got = store.get("test-skill")
    assert got is not None
    assert got.description == DESC
    assert "Do the thing." in got.body
    assert got.category is None


def test_create_with_category(store):
    skill = store.create("cat-skill", DESC, category="writing")
    assert skill.category == "writing"
    assert (store.root / "writing" / "cat-skill" / "SKILL.md").exists()
    assert store.get("cat-skill").category == "writing"


def test_create_rejects_bad_input_and_duplicates(store):
    with pytest.raises(ValueError, match="name"):
        store.create("Not Valid!", DESC)
    with pytest.raises(ValueError, match="description"):
        store.create("fine-name", "")
    store.create("dupe", DESC)
    with pytest.raises(ValueError, match="already exists"):
        store.create("dupe", DESC)


def test_update(store):
    store.create("up-skill", DESC, body="old body")
    updated = store.update("up-skill", body="new body", description="New desc. Use anew.")
    assert updated.description == "New desc. Use anew."
    assert updated.body.strip() == "new body"
    with pytest.raises(ValueError):
        store.update("up-skill")  # nothing to change
    with pytest.raises(ValueError):
        store.update("ghost", body="x")


# ---- lazy body + mtime invalidation -----------------------------------------
def test_body_is_lazy_loaded(store, root):
    _write_skill(root, "lazy-skill", body="# Lazy\nthe body text")
    skill = store.discover()[0]
    assert skill._body is None  # not read yet
    assert "the body text" in skill.body
    assert skill._body is not None  # cached after first access


def test_mtime_invalidation(store, root):
    skill_dir = _write_skill(root, "mut-skill", description="Old words. Use early.")
    assert store.get("mut-skill").description.startswith("Old")
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(skill_file.read_text().replace("Old words", "New words"))
    bump = time.time() + 5
    os.utime(skill_file, (bump, bump))  # defeat coarse mtime granularity
    assert store.get("mut-skill").description.startswith("New")


# ---- archive / unarchive (never delete) -------------------------------------
def test_archive_and_unarchive(store, root):
    store.create("arch-skill", DESC, body="keep me")
    archived = store.archive("arch-skill")
    assert archived.state == "archived"
    assert (root / ".archive" / "arch-skill" / "SKILL.md").exists()
    assert not (root / "arch-skill").exists()
    assert store.list() == []  # hidden by default
    assert [s.name for s in store.list(include_archived=True)] == ["arch-skill"]

    restored = store.unarchive("arch-skill")
    assert restored.state == "active"
    assert (root / "arch-skill" / "SKILL.md").exists()
    assert "keep me" in restored.body


def test_unarchive_restores_category(store, root):
    store.create("cat-arch", DESC, category="ops")
    store.archive("cat-arch")
    assert not (root / "ops").exists()  # empty category dir tidied
    restored = store.unarchive("cat-arch")
    assert restored.category == "ops"
    assert (root / "ops" / "cat-arch" / "SKILL.md").exists()


# ---- pin / unpin -------------------------------------------------------------
def test_pin_survives_rediscovery(store, root):
    store.create("pin-skill", DESC)
    assert store.pin("pin-skill").state == "pinned"
    fresh = SkillStore(root=root)  # new store, no warm cache
    assert fresh.get("pin-skill").state == "pinned"
    assert [s.name for s in fresh.list()] == ["pin-skill"]
    assert fresh.unpin("pin-skill").state == "active"


def test_pin_archived_skill_rejected(store):
    store.create("frozen", DESC)
    store.archive("frozen")
    with pytest.raises(ValueError, match="archived"):
        store.pin("frozen")


# ---- provenance ---------------------------------------------------------------
def test_agent_created_provenance(store, root):
    store.create("agent-skill", DESC)
    _write_skill(root, "user-skill")
    assert store.get("agent-skill").created_by == "agent"
    assert store.get("user-skill").created_by == "user"


# ---- loader: index block -------------------------------------------------------
def test_index_block_empty_and_formatting(store, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", store)
    assert loader_mod.skill_index_block() == ""
    store.create("idx-skill", "Indexes things. Use when indexing.")
    block = loader_mod.skill_index_block()
    assert "# Skills" in block
    assert "- idx-skill: Indexes things. Use when indexing." in block
    assert "openpup_skill" in block


def test_index_block_cap(store, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", store)
    for i in range(35):
        store.create(f"skill-{i:02d}", f"Skill number {i}. Use for cap testing.")
    block = loader_mod.skill_index_block()
    assert block.count("\n- ") == 30
    assert "...and 5 more" in block


def test_index_block_excludes_archived(store, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", store)
    store.create("shown", DESC)
    store.create("hidden", DESC)
    store.archive("hidden")
    block = loader_mod.skill_index_block()
    assert "- shown:" in block
    assert "hidden" not in block


# ---- prompting integration ------------------------------------------------------
def test_prompt_includes_skill_index(store, monkeypatch):
    monkeypatch.setattr(store_mod, "_store", store)
    store.create("prompt-skill", "Prompts things. Use inside prompts.")
    # Lean mode (the default) deliberately omits the skill index; the index
    # is a full-prompt layer.
    monkeypatch.setenv("OPENPUP_LEAN_PROMPT", "false")
    from openpup.config import get_settings

    get_settings.cache_clear()
    from openpup import prompting

    prompt = prompting.build_system_prompt()
    assert "# Skills" in prompt
    assert "- prompt-skill: Prompts things. Use inside prompts." in prompt


# ---- singleton + settings wiring --------------------------------------------------
def test_default_root_follows_state_dir(tmp_path, monkeypatch):
    from openpup.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "state_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(store_mod, "_store", None)
    singleton = store_mod.get_skill_store()
    assert singleton.root == tmp_path / "skills"
    assert store_mod.get_skill_store() is singleton


# ---- security regressions ---------------------------------------------------
def test_unarchive_ignores_traversal_category(store, root):
    """metadata.category from frontmatter must never become a path escape."""
    store.create("escapee", DESC)
    store.archive("escapee")
    skill_file = root / ".archive" / "escapee" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text().replace("state: archived", "state: archived\n  category: ../../evil")
    )
    restored = store.unarchive("escapee")
    assert restored.path == root / "escapee"
    assert (root / "escapee" / "SKILL.md").is_file()
    assert not (root.parent.parent / "evil").exists()


def test_update_metadata_refuses_corrupting_write(root):
    """A rewrite that wouldn't re-validate (here: no description) is skipped."""
    from openpup.skills.store import update_metadata

    skill_dir = root / "broken"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("---\nname: broken\n---\n\nBody.\n")
    before = skill_file.read_text()
    assert update_metadata(skill_file, {"last_used": "2025-01-01"}) is False
    assert skill_file.read_text() == before


def test_update_metadata_round_trips_valid_skill(root):
    from openpup.skills.store import update_metadata

    _write_skill(root, "fine")
    skill_file = root / "fine" / "SKILL.md"
    assert update_metadata(skill_file, {"last_used": "2025-01-01"}) is True
    frontmatter, body = parse_frontmatter(skill_file.read_text())
    assert frontmatter["metadata"]["last_used"] == "2025-01-01"
    assert "Instructions." in body
