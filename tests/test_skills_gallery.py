"""Tests for the community skill gallery.

Covers registry parsing, search, install (with mocked fetch), and the
publish (registry authoring) path.
"""

import json
from unittest import mock

import pytest

from openpup.skills_gallery import (
    DEFAULT_REGISTRY_URL,
    GalleryEntry,
    Registry,
    default_registry_url,
    install_entry,
    load_registry_file,
    publish,
    search,
    validate_skill_name,
)


# ---------------------------------------------------------------------------
# Registry parsing & entry model
# ---------------------------------------------------------------------------
SAMPLE_REGISTRY = {
    "schema_version": 1,
    "skills": [
        {
            "name": "summarize-url",
            "description": "Fetch and summarize a URL via the pup.",
            "category": "web",
            "tags": ["summary", "fetch"],
            "source": {
                "type": "github",
                "repo": "alice/openpup-skills",
                "path": "skills/summarize-url/SKILL.md",
                "commit": "abc123",
            },
        },
        {
            "name": "log-meal",
            "description": "Track meals.",
            "category": "health",
            "tags": ["food"],
            "source": {
                "type": "github",
                "repo": "bob/openpup",
                "path": "registry/skills/log-meal/SKILL.md",
            },
        },
        {
            "name": "remote-fetch",
            "description": "Pointer to an external URL.",
            "source": {
                "type": "url",
                "url": "https://example.com/skills/remote-fetch/SKILL.md",
            },
        },
    ],
}


class TestGalleryEntry:
    def test_from_dict_minimal(self):
        e = GalleryEntry.from_dict({"name": "x", "description": "y"})
        assert e.name == "x"
        assert e.source_type == "github"

    def test_fetch_url_github_with_commit(self):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][0])
        url = e.fetch_url
        assert "alice/openpup-skills" in url
        assert "abc123" in url
        assert "summarize-url" in url  # path

    def test_fetch_url_github_no_commit_uses_main(self):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][1])
        url = e.fetch_url
        assert "main" in url  # default branch when no commit
        assert "log-meal" in url

    def test_fetch_url_url_source(self):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][2])
        assert e.fetch_url == "https://example.com/skills/remote-fetch/SKILL.md"

    def test_to_dict_round_trip(self):
        original = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][0])
        raw = original.to_dict()
        # Round-trip back through from_dict.
        restored = GalleryEntry.from_dict(raw)
        assert restored.name == original.name
        assert restored.fetch_url == original.fetch_url


class TestRegistry:
    def test_from_dict_valid(self):
        reg = Registry.from_dict(SAMPLE_REGISTRY)
        assert reg.schema_version == 1
        assert len(reg.skills) == 3

    def test_unsupported_schema_version(self):
        bad = {"schema_version": 999, "skills": []}
        with pytest.raises(ValueError, match="unsupported"):
            Registry.from_dict(bad)

    def test_parse_bytes(self):
        reg = Registry.parse(json.dumps(SAMPLE_REGISTRY).encode())
        assert len(reg.skills) == 3

    def test_load_registry_file(self, tmp_path):
        path = tmp_path / "skills.json"
        path.write_text(json.dumps(SAMPLE_REGISTRY))
        reg = load_registry_file(path)
        assert len(reg.skills) == 3


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class TestSearch:
    def test_empty_query_returns_all(self):
        reg = Registry.from_dict(SAMPLE_REGISTRY)
        results = search(reg, "")
        assert len(results) == 3

    def test_substring_match(self):
        reg = Registry.from_dict(SAMPLE_REGISTRY)
        results = search(reg, "summarize")
        assert len(results) == 1
        assert results[0].name == "summarize-url"

    def test_search_by_tag(self):
        reg = Registry.from_dict(SAMPLE_REGISTRY)
        results = search(reg, "food")
        assert len(results) == 1
        assert results[0].name == "log-meal"

    def test_search_limit(self):
        reg = Registry.from_dict(SAMPLE_REGISTRY)
        results = search(reg, "", limit=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
class TestInstall:
    def test_install_drops_file(self, tmp_path):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][0])
        body = "---\nname: summarize-url\ndescription: test\n---\n# Body\n"
        skills_root = tmp_path / "skills"
        result = install_entry(e, skills_root, body=body)
        assert result.exists()
        assert result.read_text().startswith("---")
        # Skill is dropped directly under skills_root (no category dir).
        assert result.parent.parent == skills_root

    def test_install_creates_category_directory(self, tmp_path):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][1])
        body = "---\nname: log-meal\ndescription: meal tracker\n---\n# Body\n"
        skills_root = tmp_path / "skills"
        result = install_entry(e, skills_root, body=body)
        assert result.parent.name == "log-meal"
        assert result.parent.parent == skills_root

    def test_install_fetches_body_when_not_provided(self, tmp_path):
        e = GalleryEntry.from_dict(SAMPLE_REGISTRY["skills"][0])
        body = "---\nname: summarize-url\ndescription: test\n---\n# Body\n"
        skills_root = tmp_path / "skills"

        with mock.patch("openpup.skills_gallery._fetch", return_value=body) as m:
            install_entry(e, skills_root)
            m.assert_called_once()
            url_arg = m.call_args.args[0]
            assert "summarize-url" in url_arg


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------
class TestPublish:
    def test_publish_creates_registry(self, tmp_path):
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: myskill\ndescription: A test skill.\n---\n# Body\n"
        )
        registry_path = tmp_path / "skills.json"
        result = publish(skill_dir, registry_path)
        assert result.entry.name == "myskill"
        assert result.registry_path == registry_path
        loaded = load_registry_file(registry_path)
        assert len(loaded.skills) == 1
        assert loaded.skills[0].name == "myskill"
        assert loaded.skills[0].source_type == "github"

    def test_publish_appends_to_existing(self, tmp_path):
        registry_path = tmp_path / "skills.json"
        registry_path.write_text(json.dumps(SAMPLE_REGISTRY))

        skill_dir = tmp_path / "newskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: newskill\ndescription: Another one.\ncategory: ops\n---\n# Body\n"
        )
        result = publish(skill_dir, registry_path, tags=("ops", "new"))
        assert result.entry.category == "ops"
        assert "ops" in result.entry.tags

        loaded = load_registry_file(registry_path)
        assert len(loaded.skills) == 4  # 3 original + 1 new
        names = {s.name for s in loaded.skills}
        assert "newskill" in names
        assert "summarize-url" in names  # still there

    def test_publish_replaces_same_name(self, tmp_path):
        registry_path = tmp_path / "skills.json"
        registry_path.write_text(json.dumps(SAMPLE_REGISTRY))
        skill_dir = tmp_path / "summarize-url"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: summarize-url\ndescription: Updated description.\n---\n# Body\n"
        )
        publish(skill_dir, registry_path)
        loaded = load_registry_file(registry_path)
        # Still 3 entries (no duplicate), and the description updated.
        assert len(loaded.skills) == 3
        e = next(s for s in loaded.skills if s.name == "summarize-url")
        assert "Updated" in e.description

    def test_publish_missing_skill_md_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            publish(tmp_path / "no-such-skill", tmp_path / "reg.json")

    def test_publish_invalid_frontmatter_raises(self, tmp_path):
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just a body, no frontmatter at all.")
        with pytest.raises(ValueError):
            publish(skill_dir, tmp_path / "reg.json")


# ---------------------------------------------------------------------------
# Defaults + env override
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_SKILLS_REGISTRY", raising=False)
        assert default_registry_url() == DEFAULT_REGISTRY_URL

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_SKILLS_REGISTRY", "file:///tmp/x.json")
        assert default_registry_url() == "file:///tmp/x.json"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class TestValidation:
    @pytest.mark.parametrize(
        "name",
        ["a", "ab", "my-skill", "my.skill", "x" * 63],
    )
    def test_valid_names(self, name):
        validate_skill_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "A", "My-Skill", "-leading-hyphen", "x" * 64, "bad space", "x/y"],
    )
    def test_invalid_names(self, name):
        with pytest.raises(ValueError):
            validate_skill_name(name)
