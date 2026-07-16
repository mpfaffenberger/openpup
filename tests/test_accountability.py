"""Tests for accountability module."""

import time

from openpup.accountability import Commitment, CommitmentStore


class TestCommitment:
    def test_status_pending(self):
        c = Commitment(text="x", due_ts=0)
        assert c.status == "pending"

    def test_status_done(self):
        c = Commitment(text="x", due_ts=0, done_ts=1)
        assert c.status == "done"

    def test_status_abandoned(self):
        c = Commitment(text="x", due_ts=0, abandoned_ts=1)
        assert c.status == "abandoned"

    def test_round_trip(self):
        c = Commitment(text="x", due_ts=123)
        d = c.to_dict()
        c2 = Commitment.from_dict(d)
        assert c2.text == "x"
        assert c2.due_ts == 123


class TestStore:
    def test_add_and_list(self, tmp_path):
        s = CommitmentStore(tmp_path / "a.json")
        s.add("x", 123)
        s.add("y", 456)
        items = s.list()
        assert len(items) == 2

    def test_due_today(self, tmp_path):
        s = CommitmentStore(tmp_path / "a.json")
        today = 1700000000
        s.add("today", today)
        s.add("next week", today + 86400 * 7)
        due = s.due_today(today)
        assert len(due) == 1
        assert due[0].text == "today"

    def test_complete(self, tmp_path):
        s = CommitmentStore(tmp_path / "a.json")
        s.add("x", 123)
        items = s.list()
        key = f"{items[0].created_ts}:x"
        s.complete(key)
        # Status now done.
        items = s.list("done")
        assert len(items) == 1
        assert items[0].done_ts is not None

    def test_abandon(self, tmp_path):
        s = CommitmentStore(tmp_path / "a.json")
        s.add("x", 123)
        items = s.list()
        key = f"{items[0].created_ts}:x"
        s.abandon(key)
        items = s.list("abandoned")
        assert len(items) == 1
