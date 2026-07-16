"""Code-aware indexing: symbol-aware chunking for code repos in RAG.

Reads Python files and chunks at top-level definitions (functions, classes,
modules). Each chunk has a ``symbol`` so search results can be presented
in terms of "this function" rather than "this snippet of text".

v1 supports Python only via the stdlib ``ast`` module. Other languages
would need a real parser (tree-sitter, libclang) and are out of scope.
"""
from __future__ import annotations

import ast
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("openpup.code_aware")


@dataclass
class CodeChunk:
    """One top-level symbol: a function or a class."""

    file: str
    symbol: str  # 'MyClass' or 'my_function'
    kind: str  # 'function' / 'class' / 'module'
    start_line: int
    end_line: int
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def chunk_python(text: str, *, filename: str = "<stdin>") -> list[CodeChunk]:
    """Symbol-aware chunking of a Python source string.

    Each top-level function or class becomes a chunk; a final "module"
    chunk covers any module-level code that doesn't belong to a symbol
    (imports, assignments, etc.).
    """
    chunks: list[CodeChunk] = []
    try:
        tree = ast.parse(text, filename)
    except SyntaxError as exc:
        logger.debug("skipping unparseable Python %s: %s", filename, exc)
        return chunks
    lines = text.splitlines(keepends=True)
    module_start = 1
    for node in tree.body:
        kind = _kind_of(node)
        if kind in ("function", "class", "async_function"):
            # Include docstring + decorators from the line range.
            start = (getattr(node, "decorator_list", [None])[0].lineno
                     if getattr(node, "decorator_list", None)
                     else node.lineno)
            chunk = CodeChunk(
                file=filename,
                symbol=node.name,
                kind="class" if kind == "class" else "function",
                start_line=start,
                end_line=node.end_lineno or node.lineno,
                source="".join(lines[start - 1 : node.end_lineno or start]),
            )
            chunks.append(chunk)
        else:
            # Module-level statement. Collect into a "module" chunk.
            chunks.append(
                CodeChunk(
                    file=filename,
                    symbol=f"<{kind}>",
                    kind="module",
                    start_line=module_start,
                    end_line=node.end_lineno or node.lineno,
                    source="".join(lines[module_start - 1 : node.end_lineno or module_start]),
                )
            )
        module_start = (node.end_lineno or node.lineno) + 1
    # Trailing module-level code.
    if module_start <= len(lines):
        chunks.append(
            CodeChunk(
                file=filename,
                symbol="<module>",
                kind="module",
                start_line=module_start,
                end_line=len(lines),
                source="".join(lines[module_start - 1 :]),
            )
        )
    return chunks


def chunk_path(path: Path) -> list[CodeChunk]:
    """Chunk a Python file on disk."""
    try:
        text = path.read_text()
    except Exception:
        return []
    return chunk_python(text, filename=str(path))


def _kind_of(node: ast.AST) -> str:
    return {
        ast.FunctionDef: "function",
        ast.AsyncFunctionDef: "async_function",
        ast.ClassDef: "class",
        ast.Import: "import",
        ast.ImportFrom: "import_from",
        ast.Assign: "assign",
        ast.Expr: "expr",
    }.get(type(node), type(node).__name__.lower())
