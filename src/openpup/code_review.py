"""Code review facade for OpenPup.

v1 is a deterministic stub that returns a structured review based on a
handful of regex heuristics (size, TODO markers, syntax). A real LLM-
based review is a follow-up commit so v1 stays focused on the framework.

Output shape (the same real backends should produce):
  {
    "summary": str,
    "findings": [{"severity": "info"|"warn"|"blocker", "line": int?, "msg": str}],
    "score": int (0..100),
  }
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Literal

logger = logging.getLogger("openpup.code_review")

Severity = Literal["info", "warn", "blocker"]


@dataclass
class Finding:
    severity: str
    msg: str
    line: int = 0


def review(text: str) -> dict:
    """Review a diff or source file. Returns a structured review dict."""
    findings: list[Finding] = []
    lines = text.splitlines()
    score = 100

    if len(text) > 50_000:
        findings.append(Finding("warn", "very large diff (>50K chars); consider splitting"))
        score -= 5

    todo_count = 0
    for i, line in enumerate(lines, start=1):
        if "TODO" in line:
            todo_count += 1
        if re.search(r"\bprint\(", line):
            findings.append(Finding("info", "print() call; consider logging", line=i))
            score -= 2
        if "XXX" in line or "FIXME" in line:
            findings.append(Finding("warn", "FIXME / XXX marker", line=i))
            score -= 5
    if todo_count:
        findings.append(Finding("info", f"{todo_count} TODO marker(s)"))
        score -= min(todo_count, 5)

    score = max(0, score)
    if not findings:
        findings.append(Finding("info", "no obvious issues"))
    summary = _summary(score, findings)
    return {
        "summary": summary,
        "findings": [asdict(f) for f in findings],
        "score": score,
    }


def _summary(score: int, findings: list[Finding]) -> str:
    blockers = sum(1 for f in findings if f.severity == "blocker")
    warns = sum(1 for f in findings if f.severity == "warn")
    return f"score={score}/100; {blockers} blocker(s), {warns} warning(s)"
