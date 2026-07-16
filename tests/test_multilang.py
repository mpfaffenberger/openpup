"""Tests for multilang detection."""

from openpup.multilang import detect, default_language


def test_english():
    assert detect("Hello, world!").code == "en"


def test_chinese():
    assert detect("\u4f60\u597d\u4e16\u754c").code == "zh"


def test_arabic():
    assert detect("\u0645\u0631\u062d\u0628\u0627").code == "ar"


def test_cyrillic():
    assert detect("\u041f\u0440\u0438\u0432\u0435\u0442").code == "ru"


def test_empty_returns_default():
    assert detect("").code == "en"


def test_default_language_env(monkeypatch):
    monkeypatch.setenv("OPENPUP_DEFAULT_LANGUAGE", "fr")
    assert default_language() == "fr"
