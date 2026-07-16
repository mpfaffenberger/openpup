"""Tests for the A/B testing module."""

from openpup.ab_test import Experiment, ExperimentStore, assign, record, win_rate


class TestAssign:
    def test_deterministic(self):
        e = Experiment(name="t1", prompt_a="a", prompt_b="b")
        a1 = assign(e, "alice")
        a2 = assign(e, "alice")
        assert a1 == a2

    def test_different_owners_different_variants(self):
        # Over many owners, both variants appear.
        e = Experiment(name="t1", prompt_a="a", prompt_b="b")
        seen = {assign(e, f"u{i}") for i in range(50)}
        assert len(seen) == 2  # both 'a' and 'b' seen


class TestRecord:
    def test_a_win(self):
        e = Experiment(name="t", prompt_a="a", prompt_b="b")
        # Force 'a' assignment.
        owner = "x"
        while assign(e, owner) != "a":
            owner = "x" + str(hash(owner))
        record(e, owner, "win")
        assert e.a_wins == 1


class TestWinRate:
    def test_none_when_no_data(self):
        e = Experiment(name="t", prompt_a="a", prompt_b="b")
        assert win_rate(e, "a") is None

    def test_all_wins(self):
        e = Experiment(name="t", prompt_a="a", prompt_b="b")
        e.a_wins = 5
        e.a_losses = 0
        assert win_rate(e, "a") == 1.0

    def test_half(self):
        e = Experiment(name="t", prompt_a="a", prompt_b="b")
        e.a_wins = 5
        e.a_losses = 5
        assert win_rate(e, "a") == 0.5


class TestStore:
    def test_start_and_list(self, tmp_path):
        s = ExperimentStore(tmp_path / "a.json")
        s.start(Experiment(name="t1", prompt_a="a", prompt_b="b"))
        s.start(Experiment(name="t2", prompt_a="c", prompt_b="d"))
        exps = s.list()
        assert len(exps) == 2

    def test_stop(self, tmp_path):
        s = ExperimentStore(tmp_path / "a.json")
        s.start(Experiment(name="t1", prompt_a="a", prompt_b="b"))
        assert s.stop("t1") is True
        assert s.list() == []
        # Second stop fails.
        assert s.stop("t1") is False
