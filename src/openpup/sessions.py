"""Session transcript store (SQLite + FTS5).

Every conversation OpenPup has — per platform channel or the heartbeat's own
musings — is recorded as a *session* of timestamped messages. This gives the
agent (and its tools) a searchable, replayable history that is independent of
the kennel's semantic memory.

Design notes (inspired by hermes-agent's session DB):

* stdlib ``sqlite3`` only, one file at ``state_dir / "sessions.db"``;
* FTS5 keeps full-text search fast — detected at init and transparently
  replaced by a ``LIKE`` scan when the sqlite build lacks it;
* every public method degrades gracefully: DB errors are logged at debug
  level and callers get empty results / ``None``, never an exception.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("openpup.sessions")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    source      TEXT,
    started_at  REAL,
    last_active REAL,
    title       TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role       TEXT,
    content    TEXT,
    ts         REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(content, content='messages', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

_DEFAULT_ROLES = ("user", "assistant")


def _now() -> float:
    """Indirection over time.time() so tests can control the clock."""
    return time.time()


def _msg(row: sqlite3.Row) -> Dict[str, Any]:
    return {"id": row["id"], "role": row["role"], "content": row["content"], "ts": row["ts"]}


def _like_snippet(content: str, query: str, width: int = 80) -> str:
    """Cheap snippet for the LIKE fallback: a window around the first match."""
    idx = content.lower().find(query.lower())
    if idx < 0:
        idx = 0
    start = max(0, idx - width // 2)
    end = min(len(content), idx + len(query) + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


def _fts_query(query: str) -> str:
    """Quote each token so user text can never break FTS5 query syntax."""
    tokens = ['"{}"'.format(t.replace('"', '""')) for t in query.split()]
    return " ".join(tokens)


class SessionStore:
    """SQLite-backed transcript store with full-text search."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_sessions_path()
        self.fts_enabled = False
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            self._conn = conn
            self.fts_enabled = self._init_fts(conn)
        except Exception:
            logger.debug("session store init failed at %s", self.path, exc_info=True)

    @staticmethod
    def _init_fts(conn: sqlite3.Connection) -> bool:
        try:
            conn.executescript(_FTS_SCHEMA)
            return True
        except sqlite3.OperationalError:
            logger.debug("FTS5 unavailable; falling back to LIKE search", exc_info=True)
            return False

    # ---- writes ----------------------------------------------------------
    def append(
        self,
        session_id: str,
        source: str,
        role: str,
        content: str,
        title: Optional[str] = None,
    ) -> Optional[int]:
        """Record one message; creates the session row on first write.

        Returns the new message id, or None on failure.
        """
        if not session_id or not content or not content.strip():
            return None
        try:
            now = _now()
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO sessions(id, source, started_at, last_active, title)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (session_id, source, now, now, title),
                )
                if title is not None:
                    self._conn.execute(
                        "UPDATE sessions SET last_active = ?, title = ? WHERE id = ?",
                        (now, title, session_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE sessions SET last_active = ? WHERE id = ?", (now, session_id)
                    )
                cur = self._conn.execute(
                    "INSERT INTO messages(session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                    (session_id, role, content, now),
                )
                return cur.lastrowid
        except Exception:
            logger.debug("append failed for session %s", session_id, exc_info=True)
            return None

    # ---- search ----------------------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 5,
        role_filter: Sequence[str] = _DEFAULT_ROLES,
    ) -> List[Dict[str, Any]]:
        """Full-text search, deduped to the best hit per session."""
        if not query or not query.strip():
            return []
        try:
            roles = tuple(role_filter) or _DEFAULT_ROLES
            candidates = max(limit * 5, 25)
            with self._lock:
                if self.fts_enabled:
                    rows = self._search_fts(query, roles, candidates)
                else:
                    rows = self._search_like(query, roles, candidates)
            hits: List[Dict[str, Any]] = []
            seen: set = set()
            for row in rows:
                if row["session_id"] in seen:
                    continue
                seen.add(row["session_id"])
                hits.append(row)
                if len(hits) >= limit:
                    break
            return hits
        except Exception:
            logger.debug("search failed for %r", query, exc_info=True)
            return []

    def _search_fts(self, query: str, roles: Sequence[str], limit: int) -> List[Dict[str, Any]]:
        marks = ", ".join("?" for _ in roles)
        rows = self._conn.execute(
            f"""
            SELECT m.id AS message_id, m.session_id, m.role, m.ts,
                   snippet(messages_fts, 0, '', '', '…', 16) AS snippet,
                   s.source, s.title, s.last_active
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE messages_fts MATCH ? AND m.role IN ({marks})
            ORDER BY rank LIMIT ?
            """,
            (_fts_query(query), *roles, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _search_like(self, query: str, roles: Sequence[str], limit: int) -> List[Dict[str, Any]]:
        marks = ", ".join("?" for _ in roles)
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self._conn.execute(
            f"""
            SELECT m.id AS message_id, m.session_id, m.role, m.ts, m.content,
                   s.source, s.title, s.last_active
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.content LIKE ? ESCAPE '\\' AND m.role IN ({marks})
            ORDER BY m.ts DESC LIMIT ?
            """,
            (f"%{escaped}%", *roles, limit),
        ).fetchall()
        out = []
        for r in rows:
            hit = dict(r)
            hit["snippet"] = _like_snippet(hit.pop("content"), query)
            out.append(hit)
        return out

    # ---- reads -----------------------------------------------------------
    def messages_around(self, session_id: str, message_id: int, window: int = 5) -> Dict[str, Any]:
        """A window of +/-N messages centered on an anchor message."""
        empty = {"messages": [], "messages_before": 0, "messages_after": 0}
        try:
            with self._lock:
                anchor = self._conn.execute(
                    "SELECT id, role, content, ts FROM messages WHERE session_id = ? AND id = ?",
                    (session_id, message_id),
                ).fetchone()
                if anchor is None:
                    return empty
                before = self._conn.execute(
                    "SELECT id, role, content, ts FROM messages"
                    " WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                    (session_id, message_id, window),
                ).fetchall()
                after = self._conn.execute(
                    "SELECT id, role, content, ts FROM messages"
                    " WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                    (session_id, message_id, window),
                ).fetchall()
                count_before = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ? AND id < ?",
                    (session_id, message_id),
                ).fetchone()[0]
                count_after = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ? AND id > ?",
                    (session_id, message_id),
                ).fetchone()[0]
            messages = [_msg(r) for r in reversed(before)] + [_msg(anchor)]
            messages += [_msg(r) for r in after]
            return {
                "messages": messages,
                "messages_before": count_before - len(before),
                "messages_after": count_after - len(after),
            }
        except Exception:
            logger.debug("messages_around failed for %s/%s", session_id, message_id, exc_info=True)
            return empty

    def read_session(self, session_id: str, head: int = 20, tail: int = 10) -> Dict[str, Any]:
        """Full dump for small sessions; head+tail with a truncated flag otherwise."""
        empty = {"session": None, "messages": [], "truncated": False, "omitted": 0}
        try:
            with self._lock:
                sess = self._conn.execute(
                    "SELECT id, source, started_at, last_active, title FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if sess is None:
                    return empty
                total = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
                if total <= head + tail:
                    rows = self._conn.execute(
                        "SELECT id, role, content, ts FROM messages"
                        " WHERE session_id = ? ORDER BY id",
                        (session_id,),
                    ).fetchall()
                    messages = [_msg(r) for r in rows]
                    truncated, omitted = False, 0
                else:
                    head_rows = self._conn.execute(
                        "SELECT id, role, content, ts FROM messages"
                        " WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                        (session_id, head),
                    ).fetchall()
                    tail_rows = self._conn.execute(
                        "SELECT id, role, content, ts FROM messages"
                        " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                        (session_id, tail),
                    ).fetchall()
                    messages = [_msg(r) for r in head_rows]
                    messages += [_msg(r) for r in reversed(tail_rows)]
                    truncated, omitted = True, total - head - tail
            return {
                "session": dict(sess),
                "messages": messages,
                "truncated": truncated,
                "omitted": omitted,
            }
        except Exception:
            logger.debug("read_session failed for %s", session_id, exc_info=True)
            return empty

    def recent_sessions(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Most recently active sessions, with message count and a short preview."""
        try:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT s.id AS session_id, s.source, s.title, s.started_at, s.last_active,
                           (SELECT COUNT(*) FROM messages m
                            WHERE m.session_id = s.id) AS message_count,
                           (SELECT m.content FROM messages m
                            WHERE m.session_id = s.id ORDER BY m.id DESC LIMIT 1) AS preview
                    FROM sessions s
                    ORDER BY s.last_active DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                preview = item.get("preview") or ""
                item["preview"] = preview[:80] + ("…" if len(preview) > 80 else "")
                out.append(item)
            return out
        except Exception:
            logger.debug("recent_sessions failed", exc_info=True)
            return []

    def recent_for_source(self, source: str, limit: int = 10) -> List[Dict[str, Any]]:
        """The most recent messages for a conversation ``source`` (a
        ``platform:channel`` address), across its day-bucketed sessions, in
        chronological order (oldest first).

        Used to rehydrate a conversation's recent turns after a restart, when
        the agent's in-memory history is empty -- so the pup picks the thread
        back up instead of relying on summarized memory alone.
        """
        if not source:
            return []
        try:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT m.role, m.content, m.ts
                    FROM messages m JOIN sessions s ON s.id = m.session_id
                    WHERE s.source = ?
                    ORDER BY m.ts DESC, m.id DESC LIMIT ?
                    """,
                    (source, limit),
                ).fetchall()
            return [
                {"role": r["role"], "content": r["content"], "ts": r["ts"]}
                for r in reversed(rows)
            ]
        except Exception:
            logger.debug("recent_for_source failed for %s", source, exc_info=True)
            return []


# --- process-wide singleton ------------------------------------------------
_store: Optional[SessionStore] = None


def default_sessions_path() -> Path:
    from openpup.config import get_settings

    return get_settings().state_dir / "sessions.db"


def get_session_store() -> SessionStore:
    """Shared store so the heartbeat + agent tools see the same transcripts."""
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
