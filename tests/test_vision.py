"""Tests for the vision module."""

import pytest

from openpup import vision
from openpup.vision import DEFAULT_PROMPT, describe, is_available


class TestAvailability:
    def test_no_backend_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_VISION_BACKEND", raising=False)
        assert is_available() is False

    def test_backend_set(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_VISION_BACKEND", "openai")
        assert is_available() is True


class TestDescribe:
    def test_no_backend_returns_stub(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_VISION_BACKEND", raising=False)
        result = describe(b"fake-image-bytes")
        assert "not configured" in result
        assert "fake-image-bytes" not in result  # raw bytes not in stub

    def test_stub_includes_size(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_VISION_BACKEND", raising=False)
        result = describe(b"x" * 1024)
        assert "1024 bytes" in result

    def test_custom_prompt_in_stub(self, monkeypatch):
        monkeypatch.delenv("OPENPUP_VISION_BACKEND", raising=False)
        result = describe(b"x", prompt="what colour is the sky?")
        assert "what colour is the sky?" in result


class TestDefaults:
    def test_default_prompt_sensible(self):
        assert DEFAULT_PROMPT
        assert "describe" in DEFAULT_PROMPT.lower()
