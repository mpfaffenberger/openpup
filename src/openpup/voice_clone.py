"""Voice cloning facade (opt-in).

v1 is a stub that returns a synthetic voice_id. A real Coqui / Piper
backend is a follow-up commit so v1 stays focused on the abstraction.

Settings:
  * ``OPENPUP_VOICE_CLONE_DIR`` -- directory where samples are stored
    (default: ``~/.openpup/voice_clone``).
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger("openpup.voice_clone")


def clone_dir() -> Path:
    from openpup.config import config_home

    return Path(os.environ.get("OPENPUP_VOICE_CLONE_DIR", config_home() / "voice_clone"))


def record_sample(text: str) -> Path:
    """Pretend to record a sample. v1 just writes text to a file."""
    d = clone_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"sample-{uuid.uuid4().hex[:8]}.txt"
    p.write_text(text)
    return p


def train(samples: list[Path]) -> str:
    """Train a voice from samples. v1 returns a synthetic voice_id."""
    d = clone_dir()
    d.mkdir(parents=True, exist_ok=True)
    voice_id = f"voice-{uuid.uuid4().hex[:8]}"
    (d / f"{voice_id}.txt").write_text("\n".join(str(s) for s in samples))
    return voice_id


def is_cloned() -> bool:
    """True if a custom voice exists."""
    d = clone_dir()
    return d.exists() and any(d.glob("voice-*.txt"))
