"""Tests for the personal CRM module."""

from datetime import date, timedelta


from openpup.crm import CRMStore, Person, followups


class TestPersonDataclass:
    def test_round_trip(self):
        p = Person(name="alice", platform="telegram", channel="123", last_contact="2024-01-15")
        d = p.to_dict()
        restored = Person.from_dict(d)
        assert restored.name == "alice"
        assert restored.platform == "telegram"
        assert restored.last_contact == "2024-01-15"


class TestCRMStore:
    def test_log_creates_new(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        p = s.log("alice")
        assert p.name == "alice"
        assert p.last_contact == date.today().isoformat()

    def test_log_appends_notes(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        s.log("alice", notes="first")
        s.log("alice", notes="second")
        p = s.get("alice")
        assert "first" in p.notes
        assert "second" in p.notes

    def test_log_specific_day(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        p = s.log("alice", day="2024-01-15")
        assert p.last_contact == "2024-01-15"

    def test_upsert(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        s.upsert(Person(name="bob", platform="telegram", channel="456"))
        s.upsert(Person(name="bob", platform="discord", channel="999"))  # change platform
        p = s.get("bob")
        assert p.platform == "discord"

    def test_remove(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        s.log("alice")
        assert s.remove("alice") is True
        # Removing again: false.
        assert s.remove("alice") is False

    def test_list_sorted_by_name(self, tmp_path):
        s = CRMStore(tmp_path / "crm.json")
        for n in ["charlie", "alice", "bob"]:
            s.log(n)
        names = [p.name for p in s.list()]
        assert names == ["alice", "bob", "charlie"]


class TestFollowups:
    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        assert followups(30) == []

    def test_stale_person_returned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        s = CRMStore(tmp_path / "crm.json")
        old = (date.today() - timedelta(days=60)).isoformat()
        s.log("alice", day=old)
        results = followups(30)
        names = [p.name for p in results]
        assert "alice" in names

    def test_recent_person_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        s = CRMStore(tmp_path / "crm.json")
        s.log("alice")  # today
        results = followups(30)
        names = [p.name for p in results]
        assert "alice" not in names

    def test_no_last_contact_always_stale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        s = CRMStore(tmp_path / "crm.json")
        s.upsert(Person(name="bob"))
        results = followups(30)
        names = [p.name for p in results]
        assert "bob" in names
