"""Persistent memory with an explicit consent gate for long-term facts.

No method writes a long-term fact unless the caller passes an explicit
consent source (for example ``user_instruction`` or ``user_approval``).
Conversation messages are session context and are retained independently.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class MemoryError(Exception):
    """Base error for memory operations."""


class ConsentRequired(MemoryError):
    """Raised when a long-term write lacks explicit user consent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MemoryService:
    def __init__(self, db_path: str | Path | None = None, session_limit: int = 6):
        self.db_path = str(db_path or os.getenv("MEMORY_DB_PATH", "backend/data/memory.sqlite3"))
        self.session_limit = max(1, session_limit)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS session_messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
                    content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_session_messages_conversation
                    ON session_messages(conversation_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, text TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'fact', created_at TEXT NOT NULL,
                    last_used_at TEXT, consent_source TEXT NOT NULL
                    CHECK(consent_source IN ('user_instruction','user_approval'))
                );
                CREATE INDEX IF NOT EXISTS ix_long_term_user ON long_term_memories(user_id, created_at DESC);
            """)

    def add_message(self, conversation_id: str, role: str, content: str,
                    metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not conversation_id.strip():
            raise ValueError("conversation_id is required")
        if role not in {"user", "assistant", "tool"}:
            raise ValueError("role must be user, assistant, or tool")
        if not content.strip():
            raise ValueError("content is required")
        row = {"id": str(uuid.uuid4()), "conversation_id": conversation_id,
               "role": role, "content": content, "metadata": metadata or {}, "created_at": _now()}
        with self._connect() as db:
            db.execute("INSERT INTO session_messages VALUES (?, ?, ?, ?, ?, ?)",
                       (row["id"], conversation_id, role, content,
                        json.dumps(row["metadata"], ensure_ascii=False), row["created_at"]))
            stale = db.execute("SELECT id FROM session_messages WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?",
                               (conversation_id, self.session_limit)).fetchall()
            if stale:
                db.executemany("DELETE FROM session_messages WHERE id=?", [(r["id"],) for r in stale])
        return row

    def get_session(self, conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        limit = self.session_limit if limit is None else max(1, limit)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM session_messages WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                              (conversation_id, limit)).fetchall()
        return [{"id": r["id"], "conversation_id": r["conversation_id"], "role": r["role"],
                 "content": r["content"], "metadata": json.loads(r["metadata_json"]),
                 "created_at": r["created_at"]} for r in reversed(rows)]

    def clear_session(self, conversation_id: str) -> int:
        with self._connect() as db:
            cur = db.execute("DELETE FROM session_messages WHERE conversation_id=?", (conversation_id,))
            return cur.rowcount

    def remember(self, user_id: str, text: str, category: str = "fact",
                 consent_source: str | None = None) -> dict[str, Any]:
        """Save a long-term fact only after an explicit instruction/approval."""
        if consent_source not in {"user_instruction", "user_approval"}:
            raise ConsentRequired("Long-term memory requires explicit user instruction or approval")
        if not user_id.strip() or not text.strip():
            raise ValueError("user_id and text are required")
        memory = {"id": str(uuid.uuid4()), "user_id": user_id, "text": text.strip(),
                  "category": category.strip() or "fact", "created_at": _now(),
                  "last_used_at": None, "consent_source": consent_source}
        with self._connect() as db:
            db.execute("INSERT INTO long_term_memories VALUES (?, ?, ?, ?, ?, ?, ?)",
                       tuple(memory.values()))
        return memory

    def list_memories(self, user_id: str, touch: bool = True) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM long_term_memories WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
            if touch and rows:
                db.execute("UPDATE long_term_memories SET last_used_at=? WHERE user_id=?", (_now(), user_id))
        return [dict(row) for row in rows]

    def forget(self, user_id: str, memory_id: str | None = None, text: str | None = None) -> int:
        """Delete one memory by ID/text, or all memories for a user."""
        if memory_id:
            clause, args = "user_id=? AND id=?", (user_id, memory_id)
        elif text:
            clause, args = "user_id=? AND text=?", (user_id, text)
        else:
            clause, args = "user_id=?", (user_id,)
        with self._connect() as db:
            return db.execute(f"DELETE FROM long_term_memories WHERE {clause}", args).rowcount
