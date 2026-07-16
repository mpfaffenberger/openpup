"""Cost budgets: alert + soft-cap based on daily / weekly spend.

Wraps the existing ``cost.py`` module to compute rolling-window totals
(day / week) and emit warnings + caps when configured thresholds are hit.

Settings (env vars):
  * ``OPENPUP_BUDGET_DAILY`` -- daily limit in USD (default: no limit).
  * ``OPENPUP_BUDGET_WEEKLY`` -- weekly limit in USD (default: no limit).
  * ``OPENPUP_BUDGET_WARN_AT`` -- fraction of limit at which to warn
    (default: 0.8).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("openpup.cost_budget")

WINDOW_S = {
    "daily": 86400,
    "weekly": 86400 * 7,
}


@dataclass
class BudgetConfig:
    daily: float = 0.0  # 0 means disabled
    weekly: float = 0.0
    warn_at: float = 0.8

    @classmethod
    def from_env(cls) -> "BudgetConfig":
        return cls(
            daily=float(os.environ.get("OPENPUP_BUDGET_DAILY", "0") or 0),
            weekly=float(os.environ.get("OPENPUP_BUDGET_WEEKLY", "0") or 0),
            warn_at=float(os.environ.get("OPENPUP_BUDGET_WARN_AT", "0.8") or 0.8),
        )


@dataclass
class BudgetStatus:
    window: str
    limit: float
    spent: float
    pct: float  # 0..1+ over the limit
    warn: bool = False
    capped: bool = False

    def to_dict(self) -> dict:
        return {
            "window": self.window,
            "limit": self.limit,
            "spent": round(self.spent, 4),
            "pct": round(self.pct, 3),
            "warn": self.warn,
            "capped": self.capped,
        }


def check(
    costs: list[tuple[float, float]],
    *,
    config: BudgetConfig | None = None,
    now: float | None = None,
) -> list[BudgetStatus]:
    """Check rolling-window spend against config; return per-window status.

    ``costs`` is a list of ``(timestamp, amount)`` tuples. Order doesn't
    matter; entries older than each window are filtered.
    """
    cfg = config or BudgetConfig.from_env()
    now = now if now is not None else time.time()
    out: list[BudgetStatus] = []
    for window, limit in (("daily", cfg.daily), ("weekly", cfg.weekly)):
        if limit <= 0:
            continue
        cutoff = now - WINDOW_S[window]
        spent = sum(amt for ts, amt in costs if ts >= cutoff)
        pct = spent / limit
        warn = pct >= cfg.warn_at
        capped = pct >= 1.0
        out.append(
            BudgetStatus(
                window=window,
                limit=limit,
                spent=spent,
                pct=pct,
                warn=warn,
                capped=capped,
            )
        )
    return out
