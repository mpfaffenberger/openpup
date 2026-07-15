"""Community skill gallery for OpenPup.

A "gallery" is a registry of community-contributed skills, stored as a single
JSON index (``registry/skills.json`` in the OpenPup repo, by default). Each
entry points at a ``SKILL.md`` body (typically hosted on GitHub) that can be
fetched and installed into ``~/.openpup/skills/`` with one command.

Registry schema (``registry.json``)::

    {
      "schema_version": 1,
      "skills": [
        {
          "name": "summarize-url",
          "description": "Fetch and summarize a URL.",
          "category": "web",
          "tags": ["summary", "fetch"],
          "source": {
            "type": "github",                   # "github" | "url"
            "repo": "mpfaffenberger/openpup",   # GitHub owner/repo
            "path": "registry/skills/summarize-url/SKILL.md",
            "commit": "abc123..."                # optional SHA; pin for reproducibility
          }
        }
      ]
    }

This module deliberately stays small. The skill store (``openpup.skills.store``)
remains the single source of truth for what ends up on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("openpup.skills_gallery")

DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/mpfaffenberger/openpup/main/registry/skills.json"
)


# ---------------------------------------------------------------------------
# Registry model
# ---------------------------------------------------------------------------
@dataclass
class GalleryEntry:
    name: str
    description: str
    category: str = ""
    tags: list[str] = field(default_factory=list)
    source_type: str = "github"  # "github" | "url"
    source_repo: str = ""
    source_path: str = ""
    source_commit: str = ""
    source_url: str = ""

    @property
    def fetch_url(self) -> str:
        """Resolve the actual URL to download the SKILL.md from."""
        if self.source_type == "github" and self.source_repo and self.source_path:
            url = (
                f"https://raw.githubusercontent.com/{self.source_repo}/{self.source_commit or 'main'}/"
                f"{self.source_path.lstrip('/')}"
            )
            if self.source_commit:
                return url
            # Pin to 'main' as fallback when no commit
            return url
        if self.source_type == "url" and self.source_url:
            return self.source_url
        raise ValueError(f"gallery entry {self.name!r} has no resolvable source URL")

    @classmethod
    def from_dict(cls, raw: dict) -> "GalleryEntry":
        src = raw.get("source") or {}
        return cls(
            name=str(raw["name"]).strip(),
            description=str(raw.get("description", "")).strip(),
            category=str(raw.get("category", "")).strip(),
            tags=[str(t) for t in raw.get("tags", [])],
            source_type=str(src.get("type", "github")),
            source_repo=str(src.get("repo", "")),
            source_path=str(src.get("path", "")),
            source_commit=str(src.get("commit", "")),
            source_url=str(src.get("url", "")),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.category:
            out["category"] = self.category
        if self.tags:
            out["tags"] = list(self.tags)
        if self.source_type == "url":
            out["source"] = {"type": "url", "url": self.source_url}
        else:
            out["source"] = {
                "type": "github",
                "repo": self.source_repo,
                "path": self.source_path,
            }
            if self.source_commit:
                out["source"]["commit"] = self.source_commit
        return out


@dataclass
class Registry:
    schema_version: int
    skills: list[GalleryEntry]
    raw: dict

    @classmethod
    def from_dict(cls, raw: dict) -> "Registry":
        version = int(raw.get("schema_version", 0))
        if version != 1:
            raise ValueError(f"unsupported registry schema_version {version} (expected 1)")
        entries = [GalleryEntry.from_dict(s) for s in raw.get("skills", [])]
        return cls(schema_version=version, skills=entries, raw=raw)

    @classmethod
    def parse(cls, blob: bytes) -> "Registry":
        return cls.from_dict(json.loads(blob.decode("utf-8")))


# ---------------------------------------------------------------------------
# Registry sources
# ---------------------------------------------------------------------------
def default_registry_url() -> str:
    """Honour the OPENPUP_SKILLS_REGISTRY override, else the default URL."""
    return os.environ.get("OPENPUP_SKILLS_REGISTRY") or DEFAULT_REGISTRY_URL


def fetch_registry(url: Optional[str] = None) -> Registry:
    """Download and parse the registry JSON. Raises on network/parse errors."""
    import urllib.request

    target = url or default_registry_url()
    with urllib.request.urlopen(target, timeout=15) as resp:  # noqa: S310 - admin-only
        return Registry.parse(resp.read())


def load_registry_file(path: Path) -> Registry:
    """Parse a local registry JSON (for offline dev and tests)."""
    return Registry.parse(Path(path).read_bytes())


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(registry: Registry, query: str = "", limit: int = 20) -> list[GalleryEntry]:
    """Substring match across name, description, category, tags. Empty query = all."""
    q = (query or "").lower().strip()
    out: list[GalleryEntry] = []
    for entry in registry.skills:
        haystack = " ".join([entry.name, entry.description, entry.category, *entry.tags]).lower()
        if not q or q in haystack:
            out.append(entry)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
def install_entry(
    entry: GalleryEntry,
    skills_root: Path,
    body: Optional[str] = None,
) -> Path:
    """Drop a skill into ``skills_root/<category?>/<name>/SKILL.md``.

    Returns the path of the new SKILL.md. If ``body`` is None, fetches it via
    the entry's ``fetch_url``.
    """
    if not entry.name:
        raise ValueError("entry has no name")
    validate_skill_name(entry.name)
    if body is None:
        body = _fetch(entry.fetch_url)

    # Build the directory. Skills in the registry are placed without a category
    # in front (the category is a metadata hint, not a directory).
    target_dir = skills_root / entry.name
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_file = target_dir / "SKILL.md"

    # The gallery ships a SKILL.md body (frontmatter + body). Use as-is so
    # existing frontmatter metadata is preserved.
    skill_file.write_text(body, encoding="utf-8")
    logger.info("installed skill %r to %s", entry.name, skill_file)
    return skill_file


def _fetch(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 - admin-only
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Publish (package a local skill for the registry)
# ---------------------------------------------------------------------------
@dataclass
class PublishResult:
    entry: GalleryEntry
    registry_path: Path


def publish(
    skill_dir: Path,
    registry_path: Path,
    tags: Iterable[str] = (),
    commit_sha: str = "",
    repo: str = "mpfaffenberger/openpup",
) -> PublishResult:
    """Add a local skill to ``registry_path`` JSON (creating it if missing).

    The skill directory must contain a ``SKILL.md`` with ``name`` and
    ``description`` frontmatter keys (matching the on-disk Skill model).

    Returns the :class:`GalleryEntry` plus the path of the registry file
    written.
    """
    skill_md = Path(skill_dir) / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"no SKILL.md at {skill_md}")

    text = skill_md.read_text(encoding="utf-8")
    frontmatter, _ = _split_frontmatter(text)
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    if not name or not description:
        raise ValueError("SKILL.md frontmatter must include 'name' and 'description' keys")
    validate_skill_name(name)
    category = str(frontmatter.get("category", "")).strip() or ""
    rel_path = f"registry/skills/{name}/SKILL.md"

    entry = GalleryEntry(
        name=name,
        description=description,
        category=category,
        tags=list(tags),
        source_type="github",
        source_repo=repo,
        source_path=rel_path,
        source_commit=commit_sha,
    )

    # Load or create the registry file
    if registry_path.exists():
        registry = load_registry_file(registry_path)
        # Replace existing entry with same name, else append.
        registry.skills = [s for s in registry.skills if s.name != name]
        registry.skills.append(entry)
    else:
        registry = Registry(schema_version=1, skills=[entry], raw={})

    _write_registry(registry, registry_path)
    return PublishResult(entry=entry, registry_path=registry_path)


def _write_registry(registry: Registry, path: Path) -> None:
    """Write the registry JSON to ``path`` (overwriting)."""
    out = {
        "schema_version": registry.schema_version,
        "skills": [e.to_dict() for e in registry.skills],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter parsing (minimal; does not require PyYAML)
# ---------------------------------------------------------------------------
def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from a SKILL.md body.

    OpenPup uses ``---`` delimited YAML frontmatter. We avoid PyYAML for
    minimal deps by parsing simple ``key: value`` pairs only.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    out: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out, body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


def validate_skill_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            f"invalid skill name {name!r}: must be lowercase, 1-63 chars, "
            "start with letter/digit, contain only [a-z0-9._-]"
        )
