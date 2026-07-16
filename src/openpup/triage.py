"""Inbox triage rules: condition-action rules for incoming messages.

A rule has a condition (matches by sender / subject regex) and an action
(archive / label / reply / drop). Storage at
``~/.openpup/triage_rules.json``.

v1 supports these actions:
  * ``archive`` -- mark as read + skip notification.
  * ``label``   -- add a tag.
  * ``reply``   -- send a fixed reply.
  * ``drop``    -- skip entirely.

A rule engine applies them in order; the first match wins.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger("openpup.triage")

DEFAULT_STORE = "triage_rules.json"
Action = Literal["archive", "label", "reply", "drop"]


@dataclass
class TriageRule:
    name: str
    sender_regex: str = ""
    subject_regex: str = ""
    body_regex: str = ""
    action: str = "archive"  # one of Action
    label: str = ""
    reply_text: str = ""

    def matches(self, sender: str, subject: str, body: str) -> bool:
        for pattern, value in (
            (self.sender_regex, sender),
            (self.subject_regex, subject),
            (self.body_regex, body),
        ):
            if pattern and not re.search(pattern, value):
                return False
        return True


class RuleStore:
    """JSON-backed store of triage rules."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[TriageRule]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            return []
        return [TriageRule(**r) for r in raw.get("rules", [])]

    def _save(self, rules: list[TriageRule]) -> None:
        out = {"rules": [asdict(r) for r in rules]}
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def add(self, rule: TriageRule) -> TriageRule:
        rules = self._load()
        # Replace if same name exists.
        rules = [r for r in rules if r.name != rule.name]
        rules.append(rule)
        self._save(rules)
        return rule

    def list(self) -> list[TriageRule]:
        return self._load()

    def remove(self, name: str) -> bool:
        rules = self._load()
        new = [r for r in rules if r.name != name]
        if len(new) == len(rules):
            return False
        self._save(new)
        return True


def apply(
    rules: list[TriageRule], sender: str, subject: str, body: str
) -> Optional[TriageRule]:
    """Find the first matching rule; return it (caller acts on it)."""
    for r in rules:
        if r.matches(sender, subject, body):
            return r
    return None


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> RuleStore:
    return RuleStore(default_store_path())
