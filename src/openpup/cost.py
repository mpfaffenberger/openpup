"""Cost / token tracking for OpenPup tools.

A SQLite-backed recorder that logs ``(ts, feature, model, tokens_in,
tokens_out, cost_usd)`` per call. CLI commands surface the data sliced by
time range, feature, or model.

For v1 this is just the storage + query layer. Wiring it into
``AgentHost.run`` to capture real costs is left for a follow-up so each
feature stays a single focused commit.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openpup.cost")

DEFAULT_DB = "cost.sqlite"

# Reasonable defaults if no pricing config is provided (USD per 1K tokens).
DEFAULT_PRICING = {
    "default": {"input": 0.003, "output": 0.015},
}


@dataclass
class CostRecord:
    ts: int
    feature: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CostStore:
    """SQLite-backed cost log."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        feature TEXT NOT NULL,
        model TEXT NOT NULL,
        tokens_in INTEGER NOT NULL DEFAULT 0,
        tokens_out INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        meta TEXT
    );
    CREATE INDEX IF NOT EXISTS records_ts_idx ON records(ts);
    CREATE INDEX IF NOT EXISTS records_feature_idx ON records(feature);
    CREATE INDEX IF NOT EXISTS records_model_idx ON records(model);
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    def record(
        self,
        feature: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model: str = "default",
        cost_usd: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> CostRecord:
        """Insert a record. If ``cost_usd`` is None, derive from pricing."""
        if cost_usd is None:
            cost_usd = estimate_cost(tokens_in, tokens_out, model=model)
        rec = CostRecord(
            ts=int(time.time()),
            feature=feature,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            meta=meta,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO records(ts, feature, model, tokens_in, tokens_out, cost_usd, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.ts,
                    rec.feature,
                    rec.model,
                    rec.tokens_in,
                    rec.tokens_out,
                    rec.cost_usd,
                    json.dumps(rec.meta) if rec.meta else None,
                ),
            )
        return rec

    def query(
        self,
        since_ts: Optional[int] = None,
        until_ts: Optional[int] = None,
        feature: Optional[str] = None,
        model: Optional[str] = None,
    ) -> list[CostRecord]:
        sql = "SELECT ts, feature, model, tokens_in, tokens_out, cost_usd, meta FROM records WHERE 1=1"
        params: list[Any] = []
        if since_ts is not None:
            sql += " AND ts >= ?"
            params.append(since_ts)
        if until_ts is not None:
            sql += " AND ts <= ?"
            params.append(until_ts)
        if feature:
            sql += " AND feature = ?"
            params.append(feature)
        if model:
            sql += " AND model = ?"
            params.append(model)
        sql += " ORDER BY ts"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[CostRecord] = []
        for r in rows:
            ts, feat, mod, ti, to, cost, meta = r
            out.append(
                CostRecord(
                    ts=ts,
                    feature=feat,
                    model=mod,
                    tokens_in=ti,
                    tokens_out=to,
                    cost_usd=cost,
                    meta=json.loads(meta) if meta else None,
                )
            )
        return out

    def total(self, since_ts: Optional[int] = None) -> float:
        records = self.query(since_ts=since_ts)
        return round(sum(r.cost_usd for r in records), 6)

    def by_feature(self, since_ts: Optional[int] = None) -> dict[str, float]:
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT feature, SUM(cost_usd) FROM records"
            params: list[Any] = []
            if since_ts is not None:
                sql += " WHERE ts >= ?"
                params.append(since_ts)
            sql += " GROUP BY feature ORDER BY SUM(cost_usd) DESC"
            rows = conn.execute(sql, params).fetchall()
        return {row[0]: round(row[1], 6) for row in rows}

    def by_model(self, since_ts: Optional[int] = None) -> dict[str, float]:
        with sqlite3.connect(self.db_path) as conn:
            sql = "SELECT model, SUM(cost_usd) FROM records"
            params: list[Any] = []
            if since_ts is not None:
                sql += " WHERE ts >= ?"
                params.append(since_ts)
            sql += " GROUP BY model ORDER BY SUM(cost_usd) DESC"
            rows = conn.execute(sql, params).fetchall()
        return {row[0]: round(row[1], 6) for row in rows}


def estimate_cost(
    tokens_in: int, tokens_out: int = 0, *, model: str = "default"
) -> float:
    """Estimate cost in USD for a tool call using the loaded pricing table."""
    pricing = DEFAULT_PRICING.get(model, DEFAULT_PRICING["default"])
    in_cost = (tokens_in / 1000.0) * pricing["input"]
    out_cost = (tokens_out / 1000.0) * pricing["output"]
    return round(in_cost + out_cost, 6)


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_DB


def get_store() -> CostStore:
    return CostStore(default_store_path())
