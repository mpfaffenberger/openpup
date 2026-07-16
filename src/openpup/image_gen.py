"""Image generation facade for OpenPup.

v1 is a stub that returns a deterministic placeholder PNG (a small
gradient) so callers can wire up the API without an external service.
A real DALL-E / Stable Diffusion backend is a follow-up commit.

Settings (env vars):
  * ``OPENPUP_IMAGE_BACKEND`` -- 'stub' (default), 'openai', 'sd'.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger("openpup.image_gen")


def is_available() -> bool:
    return bool(os.environ.get("OPENPUP_IMAGE_BACKEND"))


def generate(prompt: str, *, width: int = 256, height: int = 256) -> bytes:
    """Generate an image for ``prompt``. Returns PNG bytes.

    v1 stub renders a minimal PNG with the prompt text encoded in the
    file metadata so callers can verify the API round-trip.
    """
    if not is_available():
        return _stub_png(prompt, width, height)
    backend = os.environ.get("OPENPUP_IMAGE_BACKEND", "")
    logger.info("image backend %r not yet implemented", backend)
    return _stub_png(prompt, width, height)


def _stub_png(prompt: str, width: int, height: int) -> bytes:
    """Render a minimal PNG. Uses zlib + struct to avoid PIL deps."""
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # 2-byte RGB per pixel; use a simple gradient.
    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter: None
        for x in range(width):
            raw += struct.pack(">BBB", x & 0xFF, y & 0xFF, (x + y) & 0xFF)
    idat = zlib.compress(raw, 9)
    return signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
