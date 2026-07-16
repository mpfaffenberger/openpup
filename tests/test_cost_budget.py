"""Tests for cost_budget."""

import os

import pytest

from openpup.cost_budget import BudgetConfig, check


class TestBudgetConfig:
    def test_defaults(self):
        c = BudgetConfig()
        assert c.daily == 0.0
        assert c.weekly == 0.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_BUDGET_DAILY", "0.5")
        c = BudgetConfig.from_env()
        assert c.daily == 0.5
        monkeypatch.delenv("OPENPUP_BUDGET_DAILY")

    def test_disabled_window_skipped(self):
        cfg = BudgetConfig(daily=0, weekly=2.0)
        result = check([], config=cfg)
        # Only weekly appears.
        assert len(result) == 1
        assert result[0].window == "weekly"


class TestCheck:
    def test_under_budget(self):
        cfg = BudgetConfig(daily=1.0)
        result = check([(1700000000, 0.5)], config=cfg, now=1700001000)
        assert len(result) == 1
        s = result[0]
        assert s.window == "daily"
        assert s.spent == 0.5
        assert s.warn is False
        assert s.capped is False

    def test_warn(self):
        cfg = BudgetConfig(daily=1.0, warn_at=0.5)
        result = check([(1700000000, 0.6)], config=cfg, now=1700001000)
        s = result[0]
        assert s.warn is True
        assert s.capped is False

    def test_capped(self):
        cfg = BudgetConfig(daily=1.0)
        result = check([(1700000000, 1.2)], config=cfg, now=1700001000)
        s = result[0]
        assert s.capped is True

    def test_old_entries_excluded(self):
        cfg = BudgetConfig(daily=1.0)
        old = (1700000000 - 86400 * 2, 5.0)  # 2 days old
        fresh = (1700000000, 0.2)
        result = check([old, fresh], config=cfg, now=1700001000)
        s = result[0]
        assert s.spent == 0.2  # old excluded

    def test_both_windows(self):
        cfg = BudgetConfig(daily=1.0, weekly=10.0)
        result = check([(1700000000, 0.5)], config=cfg, now=1700001000)
        assert len(result) == 2
        windows = [r.window for r in result]
        assert "daily" in windows
        assert "weekly" in windows
