from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import TurnRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def json_dump(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


class MemoryDatabase:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(database_path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    role TEXT NOT NULL,
                    name TEXT,
                    content TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    user_id TEXT,
                    source_session TEXT NOT NULL,
                    source_turn TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    supersedes TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    message_id UNINDEXED,
                    turn_id UNINDEXED,
                    user_id UNINDEXED,
                    session_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    memory_id UNINDEXED,
                    user_id UNINDEXED,
                    session_id UNINDEXED,
                    key,
                    value,
                    content,
                    tokenize='unicode61'
                );

                CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
                CREATE INDEX IF NOT EXISTS idx_turns_user ON turns(user_id);
                CREATE INDEX IF NOT EXISTS idx_memories_user_key ON memories(user_id, key, active);
                """
            )

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def create_turn(self, request: TurnRequest) -> str:
        turn_id = str(uuid.uuid4())
        timestamp = to_iso(request.timestamp)
        now = utc_now()
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    """
                    INSERT INTO turns (id, session_id, user_id, timestamp, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (turn_id, request.session_id, request.user_id, timestamp, json_dump(request.metadata), now),
                )
                for ordinal, message in enumerate(request.messages):
                    message_id = str(uuid.uuid4())
                    self.conn.execute(
                        """
                        INSERT INTO messages
                            (id, turn_id, session_id, user_id, role, name, content, ordinal, timestamp, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message_id,
                            turn_id,
                            request.session_id,
                            request.user_id,
                            message.role,
                            message.name,
                            message.content,
                            ordinal,
                            timestamp,
                            json_dump(request.metadata),
                        ),
                    )
                    self.conn.execute(
                        """
                        INSERT INTO messages_fts (message_id, turn_id, user_id, session_id, content)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (message_id, turn_id, request.user_id, request.session_id, message.content),
                    )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return turn_id

    def recent_messages(self, user_id: str | None, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        clauses = ["session_id = ?"]
        params: list[Any] = [session_id]
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = " OR ".join(clauses)
        with self.lock:
            rows = self.conn.execute(
                f"SELECT * FROM messages WHERE {where} ORDER BY timestamp DESC, ordinal DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) | {"metadata": json_load(row["metadata_json"])} for row in rows]

    def search_messages(self, query: str, user_id: str | None, session_id: str | None, limit: int = 10) -> list[dict[str, Any]]:
        tokens = [token for token in query.replace('"', " ").split() if token]
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens[:12])
        sql = """
            SELECT msg.*, bm25(messages_fts) AS rank
            FROM messages_fts
            JOIN messages msg ON msg.id = messages_fts.message_id
            WHERE messages_fts MATCH ?
        """
        params: list[Any] = [fts_query]
        scopes = []
        if user_id:
            scopes.append("msg.user_id = ?")
            params.append(user_id)
        if session_id:
            scopes.append("msg.session_id = ?")
            params.append(session_id)
        if scopes:
            sql += " AND (" + " OR ".join(scopes) + ")"
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) | {"score": 1.0, "metadata": json_load(row["metadata_json"])} for row in rows]

    def get_user_memories(self, user_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE user_id = ? ORDER BY active DESC, updated_at DESC",
                (user_id,),
            ).fetchall()
        return [self.memory_view(row) for row in rows]

    def delete_session(self, session_id: str) -> None:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute("DELETE FROM messages_fts WHERE session_id = ?", (session_id,))
                self.conn.execute("DELETE FROM memories_fts WHERE session_id = ?", (session_id,))
                self.conn.execute("DELETE FROM memories WHERE source_session = ?", (session_id,))
                self.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                self.conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def delete_user(self, user_id: str) -> None:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute("DELETE FROM messages_fts WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM memories_fts WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM turns WHERE user_id = ?", (user_id,))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def memory_view(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "key": row["key"],
            "value": row["value"],
            "confidence": float(row["confidence"]),
            "source_session": row["source_session"],
            "source_turn": row["source_turn"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "supersedes": row["supersedes"],
            "active": bool(row["active"]),
        }
