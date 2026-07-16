"""Tests for code-aware chunking."""

import pytest

from openpup.code_aware import chunk_path, chunk_python


def test_function_chunk():
    src = """\
def my_function(x):
    return x * 2

def other():
    pass
"""
    chunks = chunk_python(src, filename="t.py")
    assert len(chunks) >= 2
    funcs = [c for c in chunks if c.kind == "function"]
    assert {f.symbol for f in funcs} == {"my_function", "other"}


def test_class_chunk():
    src = """\
class Foo:
    pass

class Bar:
    pass
"""
    chunks = chunk_python(src, filename="t.py")
    classes = [c for c in chunks if c.kind == "class"]
    assert {c.symbol for c in classes} == {"Foo", "Bar"}


def test_module_chunk():
    src = "x = 1\ny = 2\n"
    chunks = chunk_python(src, filename="t.py")
    assert len(chunks) >= 1
    # No symbol-level chunks.
    assert all(c.kind == "module" for c in chunks)


def test_unparseable_returns_empty():
    src = "def broken(:\n"  # syntax error
    chunks = chunk_python(src, filename="bad.py")
    assert chunks == []


def test_chunk_path(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("def hello():\n    return 'hi'\n")
    chunks = chunk_path(p)
    assert len(chunks) >= 1
    assert any(c.symbol == "hello" for c in chunks)
