"""Image understanding (vision) for OpenPup.

A small facade for "describe this image" / "answer a question about this
image". The actual multimodal LLM call is delegated to a pluggable backend;
the base install has no vision deps so the module is safe to import.

For v1 the default backend is a stub (returns a placeholder description and
is_available() returns False). Real backends (an OpenAI-compatible vision
endpoint, a local model) can be plugged in by registering an entry point.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("openpup.vision")

DEFAULT_PROMPT = "Describe this image in detail."


def is_available() -> bool:
    """True if a real vision backend is configured.

    The base install has no vision backend; ``OPENPUP_VISION_BACKEND=openai``
    (or similar) opts in to a hosted endpoint. A local model backend could
    be added by registering one here.
    """
    return bool(os.environ.get("OPENPUP_VISION_BACKEND"))


def describe(image: bytes, *, prompt: str = DEFAULT_PROMPT) -> str:
    """Describe an image. Returns text.

    ``image`` is raw bytes (PNG / JPEG / WebP). ``prompt`` is the question
    to ask; default is a general description request.

    In v1 this returns a placeholder. When a backend is wired in (e.g. by a
    follow-up commit that adds an OpenAI-compatible client), ``is_available``
    becomes True and this function dispatches.
    """
    if not is_available():
        return _stub_description(image, prompt)
    backend = os.environ.get("OPENPUP_VISION_BACKEND")
    logger.info("vision backend %r not yet implemented", backend)
    return _stub_description(image, prompt)


def _stub_description(image: bytes, prompt: str) -> str:
    size = len(image)
    return (
        f"[vision backend not configured. Image is {size} bytes. "
        f"Set OPENPUP_VISION_BACKEND to enable; got prompt: {prompt!r}]"
    )
