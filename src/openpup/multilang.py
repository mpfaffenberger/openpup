"""Multi-language routing: detect inbound language + tag the envelope.

v1 is a deterministic Unicode-script heuristic + language-code lookup.
A real fasttext / langdetect backend lands in a follow-up commit so v1
stays focused on the abstraction.

Owner setting ``OPENPUP_DEFAULT_LANGUAGE`` (default ``en``) is the
fallback when detection is uncertain.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger("openpup.multilang")

DEFAULT_LANG = "en"

# Unicode block -> language guess. v1 supports a handful of common
# scripts so the framework can route them.
_BLOCK_LANG = {
    "CJK": "zh",  # Chinese / Japanese / Korean -- treat as zh for v1
    "HIRAGANA": "ja",
    "KATAKANA": "ja",
    "HANGUL": "ko",
    "CYRILLIC": "ru",
    "ARABIC": "ar",
    "HEBREW": "he",
    "DEVANAGARI": "hi",
    "THAI": "th",
    "LATIN": "en",
}


@dataclass
class DetectedLang:
    code: str
    confidence: float  # 0..1


def detect(text: str) -> DetectedLang:
    """Detect the dominant script in ``text`` and return a guess.

    v1 is a Unicode-block heuristic, not real ML. Confidence is a flat
    0.6 if non-Latin, 0.4 for Latin / English mixed.
    """
    if not text or not text.strip():
        return DetectedLang(code=DEFAULT_LANG, confidence=0.0)
    counts: dict[str, int] = {}
    letters = 0
    for ch in text:
        if not ch.isalpha():
            continue
        letters += 1
        try:
            name = unicodedata.name(ch, "")
        except ValueError:
            continue
        # First all-caps word is the block.
        block = name.split()[0] if name else "LATIN"
        if block == "LATIN":
            # Heuristic: if the text has more than a few non-ASCII Latin
            # chars, treat as Latin (i.e. en). v1 always reports English.
            counts["LATIN"] = counts.get("LATIN", 0) + 1
        else:
            counts[block] = counts.get(block, 0) + 1
    if not counts:
        return DetectedLang(code=DEFAULT_LANG, confidence=0.0)
    best = max(counts.items(), key=lambda kv: kv[1])
    lang = _BLOCK_LANG.get(best[0], DEFAULT_LANG)
    confidence = best[1] / max(letters, 1)
    # Confidence < 0.5 means fallback to default.
    if confidence < 0.5:
        lang = DEFAULT_LANG
        confidence = 0.0
    return DetectedLang(code=lang, confidence=round(confidence, 2))


def default_language() -> str:
    return os.environ.get("OPENPUP_DEFAULT_LANGUAGE", DEFAULT_LANG)
