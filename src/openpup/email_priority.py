"""Email priority: score each unread 1-5 and surface the top N.

In v1 the score is a deterministic heuristic: words in the subject +
priority senders bump the score. The real LLM-based scoring lands in a
follow-up commit so v1 stays focused on the framework.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("openpup.email_priority")

URGENT_TERMS = {
    "urgent",
    "asap",
    "emergency",
    "critical",
    "deadline",
    "important",
    "action",
    "required",
}

VIP_DOMAINS = {
    "ceo@",
    "cto@",
    "founder@",
    "boss@",
}

DEFAULT_WEIGHTS = {
    "urgent_term": 2.0,
    "vip_sender": 1.0,
    "long_thread": 0.3,  # bonus per additional message in thread
    "default": 1.0,
}


@dataclass
class Email:
    sender: str
    subject: str
    snippet: str = ""
    thread_count: int = 1  # number of messages in the conversation

    def score(self) -> float:
        s = DEFAULT_WEIGHTS["default"]
        subj_lower = self.subject.lower()
        for term in URGENT_TERMS:
            if term in subj_lower:
                s += DEFAULT_WEIGHTS["urgent_term"]
                break  # don't double-count
        for prefix in VIP_DOMAINS:
            if self.sender.lower().startswith(prefix):
                s += DEFAULT_WEIGHTS["vip_sender"]
                break
        if self.thread_count > 1:
            s += DEFAULT_WEIGHTS["long_thread"] * (self.thread_count - 1)
        # Clamp to 1..5
        return max(1.0, min(5.0, s))


def rank(emails: list[Email], top: int = 5) -> list[tuple[float, Email]]:
    """Return the top-N emails by score (highest first)."""
    scored = [(e.score(), e) for e in emails]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:top]
