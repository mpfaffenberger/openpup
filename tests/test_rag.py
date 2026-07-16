"""Tests for the local-files RAG module.

Covers chunking, FTS escaping, indexing, and search round-trip.
"""

from pathlib import Path


from openpup.rag import Chunk, RAGStore, _chunk_text, _fts_escape, _last_words


# ---------------------------------------------------------------------------
# FTS escape
# ---------------------------------------------------------------------------
class TestFtsEscape:
    def test_escapes_terms(self):
        assert _fts_escape("hello world") == '"hello" "world"'

    def test_escapes_special_chars(self):
        # Bare * is an FTS operator; wrap to neutralise.
        out = _fts_escape("foo* AND bar")
        assert '"foo*' in out
        assert '"AND' in out

    def test_empty(self):
        assert _fts_escape("") == '""'


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "line1\nline2\nline3"
        chunks = list(_chunk_text(text, Path("test.txt")))
        assert len(chunks) == 1
        assert chunks[0].file == "test.txt"
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 3

    def test_long_text_splits(self):
        line = "x" * 100
        text = "\n".join([line] * 30)  # 3000 chars
        chunks = list(_chunk_text(text, Path("big.txt"), chunk_size=500, overlap=50))
        assert len(chunks) > 1
        for c in chunks:
            assert c.text
            assert c.file == "big.txt"
            assert c.start_line <= c.end_line

    def test_chunk_citation_format(self):
        c = Chunk(file="x.txt", start_line=10, end_line=20, text="hello")
        assert c.citation == "x.txt:10-20"


class TestLastWords:
    def test_returns_within_budget(self):
        lines = ["a" * 50, "b" * 50, "c" * 50, "d" * 50]
        out = _last_words(lines, 150)
        total = sum(len(l) for l in out)
        assert total <= 150 + len(out) * 2  # rough budget


# ---------------------------------------------------------------------------
# RAGStore end-to-end
# ---------------------------------------------------------------------------
class TestRagStore:
    def test_index_and_search(self, tmp_path):
        # Build a small corpus.
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "a.md").write_text(
            "# Hello\n\nThis is a document about Postgres upgrade procedures.\n"
        )
        (docs / "b.md").write_text(
            "# Another\n\nThis document covers Python testing best practices.\n"
        )
        (docs / "c.txt").write_text(
            "An essay about gardening and growing tomatoes in the backyard.\n"
        )
        db = tmp_path / "rag.sqlite"
        store = RAGStore(db)
        for f in docs.iterdir():
            store.ingest_file(f)

        results = store.search("postgres", limit=5)
        assert results, "expected at least one match for 'postgres'"
        assert any("Postgres" in r.text for r in results)

        # Citations carry file:line format.
        for r in results:
            assert ":" in r.citation

    def test_ingest_idempotent(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        f = docs / "x.md"
        f.write_text("Hello world.\n\nPostgres upgrade notes here.\n")
        db = tmp_path / "rag.sqlite"
        store = RAGStore(db)
        n1 = store.ingest_file(f)
        n2 = store.ingest_file(f)
        # Second call should be a no-op (same content hash).
        assert n1 > 0
        assert n2 == 0

    def test_unsupported_format_skipped(self, tmp_path):
        # Binary file -- shouldn't crash, even if it indexes garbage.
        docs = tmp_path / "docs"
        docs.mkdir()
        f = docs / "weird.bin"
        f.write_bytes(b"\x00\x01\x02\x03binary junk that cannot decode")
        db = tmp_path / "rag.sqlite"
        store = RAGStore(db)
        # Should not raise.
        store.ingest_file(f)



