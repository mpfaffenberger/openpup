"""Local-files RAG: index a folder, search it with citations.

Indexing walks a directory, chunks each file into fragments (paragraphs, then
fixed-size fallbacks), and stores them in a SQLite FTS5 table for BM25 search.
Search returns matching chunks with ``file:line`` citations.

v1 is BM25-only — no vector embeddings. This is a deliberate YAGNI: BM25
covers most personal-vault use cases (notes, docs, READMEs) without a model
download or a vector store dependency. The schema leaves room for adding
vector embeddings later (``embeddings BLOB`` column reserved but unused).

Files handled out of the box (text-only):
- ``.md .markdown .txt .rst`` -- read as UTF-8.
- ``.py .js .ts .go .rs .java .rb .sh`` -- common source code.

PDF (``pypdf``) and DOCX (``python-docx``) are optional extras. Install with
``pip install 'openpup[rag]'`` to enable them.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("openpup.rag")

DEFAULT_DB_NAME = "rag.sqlite"
DEFAULT_CHUNK_SIZE = 800  # characters
DEFAULT_CHUNK_OVERLAP = 100  # characters


@dataclass
class Chunk:
    """A single fragment of a file, addressable by file + line range."""

    file: str
    start_line: int
    end_line: int
    text: str

    @property
    def citation(self) -> str:
        return f"{self.file}:{self.start_line}-{self.end_line}"


# ---------------------------------------------------------------------------
# SQLite / FTS5 store
# ---------------------------------------------------------------------------
class RAGStore:
    """SQLite + FTS5-backed index of file chunks."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        text TEXT NOT NULL,
        mtime INTEGER NOT NULL,
        hash TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS chunks_file_idx ON chunks(file);
    CREATE INDEX IF NOT EXISTS chunks_hash_idx ON chunks(hash);

    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text, file, start_line, end_line,
        content='chunks', content_rowid='id', tokenize='porter unicode61'
    );

    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, text, file, start_line, end_line)
        VALUES (new.id, new.text, new.file, new.start_line, new.end_line);
    END;
    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, file, start_line, end_line)
        VALUES ('delete', old.id, old.text, old.file, old.start_line, old.end_line);
    END;
    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, file, start_line, end_line)
        VALUES ('delete', old.id, old.text, old.file, old.start_line, old.end_line);
        INSERT INTO chunks_fts(rowid, text, file, start_line, end_line)
        VALUES (new.id, new.text, new.file, new.start_line, new.end_line);
    END;
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.SCHEMA)

    # -- ingest --------------------------------------------------------------
    def ingest_file(self, path: Path) -> int:
        """Index (or re-index) one file. Returns the number of chunks added."""
        path = Path(path)
        try:
            content = _read_file(path)
        except _UnsupportedFormat:
            return 0
        except Exception as exc:
            logger.debug("could not read %s: %r", path, exc)
            return 0
        if not content:
            return 0
        h = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM chunks WHERE file=? AND hash=?",
                (str(path), h),
            ).fetchone()
            if existing:
                return 0  # already indexed with same content
            # Drop existing chunks for this file (we'll re-add).
            conn.execute("DELETE FROM chunks WHERE file=?", (str(path),))
            chunks = list(_chunk_text(content, path))
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO chunks(file, start_line, end_line, text, mtime, hash) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(path), chunk.start_line, chunk.end_line, chunk.text, int(time.time()), h),
                )
            conn.commit()
            return len(chunks)

    # -- search --------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[Chunk]:
        """BM25 search. Returns chunks ordered by relevance."""
        if not query.strip():
            return []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT file, start_line, end_line, text FROM chunks_fts "
                "WHERE chunks_fts MATCH ? LIMIT ?",
                (_fts_escape(query), limit),
            ).fetchall()
        return [Chunk(file=f, start_line=s, end_line=e, text=t) for f, s, e, t in rows]


def _fts_escape(query: str) -> str:
    """Escape a user query for FTS5 (treat terms literally)."""
    # Wrap each term in quotes to neutralise operators.
    out: list[str] = []
    for term in re.findall(r"\S+", query):
        safe = term.replace('"', '""')
        out.append(f'"{safe}"')
    return " ".join(out) if out else '""'


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _chunk_text(text: str, source: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> Iterable[Chunk]:
    """Split a file into chunks (paragraph-aware)."""
    lines = text.splitlines()
    if not lines:
        return
    current_chunk: list[str] = []
    current_start = 1
    current_len = 0
    for i, line in enumerate(lines, start=1):
        if current_len + len(line) + 1 > chunk_size and current_chunk:
            chunk_text = "\n".join(current_chunk).strip()
            yield Chunk(
                file=str(source),
                start_line=current_start,
                end_line=i - 1,
                text=chunk_text,
            )
            # Overlap: keep the last `overlap` characters worth.
            keep = _last_words(current_chunk, overlap)
            current_chunk = list(keep)
            current_start = i - len(keep)
            current_len = sum(len(l) + 1 for l in current_chunk)
        current_chunk.append(line)
        current_len += len(line) + 1
    if current_chunk:
        yield Chunk(
            file=str(source),
            start_line=current_start,
            end_line=current_start + len(current_chunk) - 1,
            text="\n".join(current_chunk).strip(),
        )


def _last_words(lines: list[str], budget: int) -> list[str]:
    """Return the trailing lines whose total length fits within ``budget``."""
    out: list[str] = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > budget and out:
            break
        out.insert(0, line)
        total += len(line) + 1
    return out


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------
class _UnsupportedFormat(Exception):
    pass


def _read_file(path: Path) -> str:
    """Read text content from a file. Raises _UnsupportedFormat for binary."""
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in {".pdf"}:
        return _read_pdf(path)
    if suffix in {".docx", ".doc"}:
        return _read_docx(path)
    # Default: read as text.
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            raise _UnsupportedFormat(path)


def _read_pdf(path: Path) -> str:
    try:
        import pypdf
    except ImportError as exc:
        raise _UnsupportedFormat("install pypdf for PDF support") from exc
    reader = pypdf.PdfReader(str(path))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(parts)


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:
        raise _UnsupportedFormat("install python-docx for DOCX support") from exc
    d = docx.Document(str(path))
    return "\n".join(p.text for p in d.paragraphs)


# ---------------------------------------------------------------------------
# Default store
# ---------------------------------------------------------------------------
def default_store_path() -> Path:
    from openpup.config import config_home

    return config_home() / DEFAULT_DB_NAME


def get_store() -> RAGStore:
    return RAGStore(default_store_path())
