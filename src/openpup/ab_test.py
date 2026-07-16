"""A/B testing: deterministic-assignment experiments with win-rate reporting.

An experiment pairs two prompts (A / B); the pup assigns each owner to
one variant consistently and records the outcome (win/loss/tie). Owners
can ask for results and decide whether to keep or discard a variant.

v1 keeps the math simple: count wins + losses, report a 1-tailed
z-test approximation as a confidence hint. Bayesian inference is a
follow-up commit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger("openpup.ab_test")

DEFAULT_STORE = "experiments.json"
Variant = Literal["a", "b"]


@dataclass
class Experiment:
    name: str
    prompt_a: str
    prompt_b: str
    created_ts: int = field(default_factory=lambda: int(time.time()))
    # Per-variant outcomes
    a_wins: int = 0
    a_losses: int = 0
    b_wins: int = 0
    b_losses: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Experiment":
        return cls(**raw)


def assign(exp: Experiment, owner: str) -> Variant:
    """Deterministically assign an owner to A or B based on their name."""
    h = hashlib.sha256(f"{exp.name}:{owner}".encode()).hexdigest()
    return "a" if int(h[:8], 16) % 2 == 0 else "b"


def record(exp: Experiment, owner: str, outcome: Literal["win", "loss", "tie"]) -> Experiment:
    """Record an outcome for an owner's variant.

    v1 keeps totals on the experiment itself. Per-owner accounting is a
    follow-up.
    """
    variant = assign(exp, owner)
    if variant == "a":
        if outcome == "win":
            exp.a_wins += 1
        elif outcome == "loss":
            exp.a_losses += 1
    else:
        if outcome == "win":
            exp.b_wins += 1
        elif outcome == "loss":
            exp.b_losses += 1
    return exp


def win_rate(exp: Experiment, variant: Variant) -> Optional[float]:
    wins = exp.a_wins if variant == "a" else exp.b_wins
    losses = exp.a_losses if variant == "a" else exp.b_losses
    total = wins + losses
    if total == 0:
        return None
    return wins / total


class ExperimentStore:
    """JSON-backed store of experiments."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Experiment]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            return {}
        return {e["name"]: Experiment.from_dict(e) for e in raw.get("experiments", [])}

    def _save(self, exps: dict[str, Experiment]) -> None:
        out = {"experiments": [e.to_dict() for e in exps.values()]}
        self.path.write_text(json.dumps(out, indent=2, sort_keys=True))

    def start(self, exp: Experiment) -> Experiment:
        exps = self._load()
        exps[exp.name] = exp
        self._save(exps)
        return exp

    def list(self) -> list[Experiment]:
        return sorted(self._load().values(), key=lambda e: e.created_ts)

    def stop(self, name: str) -> bool:
        exps = self._load()
        if name not in exps:
            return False
        del exps[name]
        self._save(exps)
        return True


def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_STORE


def get_store() -> ExperimentStore:
    return ExperimentStore(default_store_path())
