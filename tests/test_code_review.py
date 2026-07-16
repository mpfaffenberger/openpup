"""Tests for code review."""

from openpup.code_review import review


def test_empty():
    r = review("")
    assert r["score"] == 100


def test_clean():
    r = review("def foo():\n    return 42\n")
    assert r["score"] == 100
    assert "no obvious issues" in str(r["findings"])


def test_print_call():
    r = review("print('hi')\n")
    assert r["score"] < 100
    assert any("print()" in f["msg"] for f in r["findings"])


def test_fixme():
    r = review("# FIXME this is broken\n")
    assert r["score"] < 100
    assert any("FIXME" in f["msg"] for f in r["findings"])


def test_score_clamp():
    # Multiple print() calls shouldn't push below 0.
    r = review("\n".join(["print('x')" for _ in range(100)]))
    assert 0 <= r["score"] <= 100
