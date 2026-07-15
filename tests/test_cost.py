"""Tests for the cost tracking module."""

import time

import pytest

from openpup.cost import CostStore, estimate_cost, get_store


class TestEstimateCost:
    def test_default_pricing(self):
        # 1000 in + 500 out at default rates.
        c = estimate_cost(1000, 500)
        assert c > 0
        assert c < 1.0  # sanity check

    def test_zero_tokens(self):
        assert estimate_cost(0) == 0.0


class TestCostStore:
    def test_record_basic(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        rec = s.record("memory_recall", tokens_in=100, tokens_out=50, model="test-model")
        assert rec.tokens_in == 100
        assert rec.tokens_out == 50
        assert rec.cost_usd > 0  # estimated from pricing

    def test_record_explicit_cost(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        rec = s.record("x", cost_usd=0.123)
        assert rec.cost_usd == 0.123

    def test_query_filter_by_ts(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        s.record("a", cost_usd=1.0)
        s.record("b", cost_usd=2.0)
        all_recs = s.query()
        assert len(all_recs) == 2
        # No records yet old enough.
        s.record("c", cost_usd=3.0)
        # Future filter excludes all (1 hour from now).
        future = int(time.time()) + 3600
        recent = s.query(since_ts=future)
        assert len(recent) == 0
        # Past filter returns everything.
        all_past = s.query(until_ts=int(time.time()) + 10)
        assert len(all_past) == 3

    def test_query_filter_by_feature(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        s.record("a", cost_usd=1.0)
        s.record("b", cost_usd=2.0)
        a_only = s.query(feature="a")
        assert len(a_only) == 1
        assert a_only[0].feature == "a"

    def test_total(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        s.record("a", cost_usd=1.0)
        s.record("b", cost_usd=2.5)
        assert s.total() == 3.5

    def test_by_feature(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        s.record("a", cost_usd=1.0)
        s.record("a", cost_usd=2.0)
        s.record("b", cost_usd=3.0)
        bf = s.by_feature()
        assert bf == {"a": 3.0, "b": 3.0}

    def test_by_model(self, tmp_path):
        s = CostStore(tmp_path / "c.db")
        s.record("a", model="model-A", cost_usd=1.0)
        s.record("b", model="model-B", cost_usd=2.0)
        bm = s.by_model()
        assert bm == {"model-A": 1.0, "model-B": 2.0}
