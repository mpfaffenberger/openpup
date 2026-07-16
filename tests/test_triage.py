"""Tests for triage rules."""

from openpup.triage import RuleStore, TriageRule, apply


class TestRule:
    def test_matches_sender(self):
        r = TriageRule(name="x", sender_regex="@github\\.com")
        assert r.matches("bot@github.com", "hi", "x")
        assert not r.matches("alice@x.com", "hi", "x")

    def test_matches_subject(self):
        r = TriageRule(name="x", subject_regex="(?i)urgent")
        assert r.matches("a", "URGENT help", "x")
        assert not r.matches("a", "lunch", "x")

    def test_matches_body(self):
        r = TriageRule(name="x", body_regex="(?i)deadline")
        assert r.matches("a", "subj", "the deadline is tomorrow")
        assert not r.matches("a", "subj", "lunch")

    def test_combined(self):
        r = TriageRule(name="x", sender_regex="alice", subject_regex="(?i)urgent")
        assert r.matches("alice@x", "URGENT help", "")
        assert not r.matches("bob@x", "URGENT help", "")
        assert not r.matches("alice@x", "lunch", "")


class TestStore:
    def test_add_and_list(self, tmp_path):
        s = RuleStore(tmp_path / "r.json")
        s.add(TriageRule(name="x", sender_regex="@github"))
        s.add(TriageRule(name="y", subject_regex="urgent"))
        rules = s.list()
        assert len(rules) == 2

    def test_add_replaces(self, tmp_path):
        s = RuleStore(tmp_path / "r.json")
        s.add(TriageRule(name="x", sender_regex="@old"))
        s.add(TriageRule(name="x", sender_regex="@new"))
        rules = s.list()
        assert len(rules) == 1
        assert rules[0].sender_regex == "@new"

    def test_remove(self, tmp_path):
        s = RuleStore(tmp_path / "r.json")
        s.add(TriageRule(name="x"))
        assert s.remove("x") is True
        # Second removal fails.
        assert s.remove("x") is False


class TestApply:
    def test_first_match_wins(self):
        rules = [
            TriageRule(name="x", sender_regex="@a.com", action="archive"),
            TriageRule(name="y", subject_regex="urgent", action="reply", reply_text="k"),
        ]
        r = apply(rules, "bob@a.com", "normal", "x")
        assert r is not None
        assert r.name == "x"

    def test_no_match(self):
        rules = [TriageRule(name="x", sender_regex="@a.com")]
        r = apply(rules, "bob@b.com", "x", "x")
        assert r is None
