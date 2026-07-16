"""Memory consolidation: identify duplicate / similar memories.

For v1 the candidate-finding is heuristic (Jaccard token overlap) -- no LLM
needed. Real semantic embeddings could be layered in later by adding an
``embeddings`` table to the kennel and using vector similarity here instead.

A "candidate group" is a set of memories that the pup thinks should be
considered for merging. The CLI / agent can then ask the owner which to
merge. v1 never auto-merges.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger("openpup.memory_consolidation")

DEFAULT_THRESHOLD = 0.4  # Jaccard similarity threshold


@dataclass
class ConsolidationCandidate:
    """A group of similar memories the owner should consider merging."""

    memories: list[str]  # text of each memory in the group
    similarity: float  # average pairwise similarity
    reason: str = ""  # human-readable rationale

    @property
    def size(self) -> int:
        return len(self.memories)


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens (alpha only)."""
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def find_candidates(
    memories: Iterable[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_group_size: int = 2,
) -> list[ConsolidationCandidate]:
    """Find groups of memories with pairwise similarity >= threshold.

    Returns candidates sorted by similarity (highest first).
    """
    mems = list(memories)
    if len(mems) < 2:
        return []
    token_sets = [_tokenize(m) for m in mems]
    # Naive O(N^2) pairwise scan; fine for small personal vaults.
    groups: list[list[int]] = []  # list of indices
    for i in range(len(mems)):
        merged = False
        for g in groups:
            sims = [_jaccard(token_sets[i], token_sets[j]) for j in g]
            avg = sum(sims) / len(sims)
            if avg >= threshold:
                g.append(i)
                merged = True
                break
        if not merged:
            # Find any group where the similarity to at least one member >= threshold.
            for g in groups:
                if any(_jaccard(token_sets[i], token_sets[j]) >= threshold for j in g):
                    g.append(i)
                    merged = True
                    break
        if not merged:
            groups.append([i])
    out: list[ConsolidationCandidate] = []
    for g in groups:
        if len(g) < min_group_size:
            continue
        sims = []
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                sims.append(_jaccard(token_sets[g[a]], token_sets[g[b]]))
        avg = sum(sims) / len(sims) if sims else 0.0
        out.append(
            ConsolidationCandidate(
                memories=[mems[i] for i in g],
                similarity=avg,
                reason=f"{len(g)} memories with avg pairwise Jaccard {avg:.2f}",
            )
        )
    out.sort(key=lambda c: c.similarity, reverse=True)
    return out


def is_exact_duplicate(memories: Iterable[str]) -> list[list[str]]:
    """Group memories that are exact (whitespace + punctuation-normalised) duplicates."""
    out: dict[str, list[str]] = defaultdict(list)
    for m in memories:
        normalised = re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", m.strip().lower())).strip()
        out[normalised].append(m)
    return [group for group in out.values() if len(group) > 1]
