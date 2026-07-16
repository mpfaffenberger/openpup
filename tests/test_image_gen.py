"""Tests for the image_gen module."""

import pytest

from openpup.image_gen import generate, is_available


class TestAvailability:
    def test_no_backend(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_IMAGE_BACKEND", raising=False)
        assert is_available() is False

    def test_with_backend(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_IMAGE_BACKEND", "openai")
        assert is_available() is True


class TestGenerate:
    def test_returns_png_bytes(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_IMAGE_BACKEND", raising=False)
        data = generate("a sunset")
        assert isinstance(data, bytes)
        assert len(data) > 0
        # PNG signature.
        assert data.startswith(b"\x89PNG\r\n\x1a\n")

    def test_custom_size(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_IMAGE_BACKEND", raising=False)
        small = generate("hi", width=8, height=8)
        big = generate("hi", width=64, height=64)
        assert len(big) > len(small)
