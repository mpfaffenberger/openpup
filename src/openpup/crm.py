"""Personal CRM: track last contact dates + notes per person.

Distinct from the contact directory (which tracks identifiers). The CRM adds
a "when did I last see X" lens + free-form notes. Used by the dashboard
followups view ("you haven't talked to alice in 60 days") and the
``openpup_crm`` agent tools.

Storage: ``~/.openpup/crm.json`` (separate from contacts.json to avoid lock
contention).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openpup.crm")

DEFAULT_STORE = "crm.json"


@dataclass
class Person:
    name: str
    platform: str = ""
    channel: str = ""
    last_contact: Optional[str] = None  # YYYY-MM-DD
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Person":
        return cls(
            name=str(raw["name"]),
            platform=str(raw.get("platform", "")),
            channel=str(raw.get("channel", "")),
            last_contact=raw.get("last_contact"),
            notes=str(raw.get("notes", "")),
            created_at=float(raw.get("created_at", time.time())),
        )


class CRMStore:
    """JSON-backed CRM with simple CRUD."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Person]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            logger.exception("could not read CRM file %s", self.path)
            return {}
        return {p["name"]: Person.from_dict(p) for p in raw.get("people", [])}

    def _save(self, people: dict[str, Person]) -> None:
        data = {"people": [p.to_dict() for p in people.values()]}
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def list(self) -> list[Person]:
        return sorted(self._load().values(), key=lambda p: p.name.lower())

    def get(self, name: str) -> Optional[Person]:
        return self._load().get(name)

    def upsert(self, person: Person) -> Person:
        people = self._load()
        people[person.name] = person
        self._save(people)
        return person

    def log(self, name: str, day: Optional[str] = None, notes: str = "") -> Person:
        """Record contact with a person on ``day`` (default today). Idempotent per day."""
        d = day or date.today().isoformat()
        people = self._load()
        person = people.get(name) or Person(name=name)
        person.last_contact = d
        if notes:
            person.notes = (person.notes + "\n" + notes).strip() if person.notes else notes
        people[name] = person
        self._save(people)
        return person

    def remove(self, name: str) -> bool:
        people = self._load()
        if name in people:
            del people[name]
            self._save(people)
            return True
        return False


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> CRMStore:
    return CRMStore(default_store_path())


def followups(threshold_days: int = 30, only_stale: bool = True) -> list[Person]:
    """Return people who haven't been contacted in ``threshold_days``.

    People with no ``last_contact`` at all are always returned (they're the most
    stale). With ``only_stale=False`` every person is returned, sorted by name.
    """
    threshold = date.today() - timedelta(days=threshold_days)
    out: list[Person] = []
    for p in get_store().list():
        if not only_stale:
            out.append(p)
            continue
        if p.last_contact is None:
            out.append(p)
            continue
        try:
            d = datetime.strptime(p.last_contact, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < threshold:
            out.append(p)
    # Sort by oldest contact first (None = most stale).
    out.sort(key=lambda p: p.last_contact or "")
    return out
