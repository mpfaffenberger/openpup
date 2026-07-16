"""Tests for the voice_clone module."""

import pytest

from openpup import voice_clone
from openpup.voice_clone import clone_dir, is_cloned, record_sample


def test_clone_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_VOICE_CLONE_DIR", str(tmp_path / "vc"))
    assert str(clone_dir()).endswith("vc")


def test_record_and_train(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENPUP_VOICE_CLONE_DIR", str(tmp_path / "vc"))
    s1 = record_sample("hello")
    s2 = record_sample("world")
    voice_id = voice_clone.train([s1, s2])
    assert voice_id.startswith("voice-")
    assert is_cloned() is True
