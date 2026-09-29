"""Локальный журнал входящих сообщений и выданных подсказок."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class MessageStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    lead_id INTEGER,
                    talk_id TEXT,
                    customer_text TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    suggestion_json TEXT,
                    note_id INTEGER,
                    error TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS messages_lead_idx ON messages(lead_id, received_at)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def insert(self, message_id: str, lead_id: int | None, talk_id: str,
               customer_text: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO messages "
                "(id,lead_id,talk_id,customer_text,received_at,status) VALUES (?,?,?,?,?,?)",
                (message_id, lead_id, talk_id, customer_text, now, "queued"),
            )
            return cursor.rowcount == 1

    def update(self, message_id: str, *, status: str, suggestion: dict[str, Any] | None = None,
               note_id: int | None = None, error: str | None = None) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE messages SET status=?, suggestion_json=COALESCE(?,suggestion_json), "
                "note_id=COALESCE(?,note_id), error=? WHERE id=?",
                (status, json.dumps(suggestion, ensure_ascii=False) if suggestion else None,
                 note_id, error, message_id),
            )

    def get(self, message_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return self._decode(row) if row else None

    def list_latest(self, limit: int = 30) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM messages ORDER BY received_at DESC LIMIT ?", (max(1, min(limit, 100)),)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def previous_messages(self, talk_id: str, current_id: str, limit: int = 5) -> list[str]:
        if not talk_id:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT customer_text FROM messages WHERE talk_id=? AND "
                "rowid < (SELECT rowid FROM messages WHERE id=?) AND received_at>=? "
                "ORDER BY rowid DESC LIMIT ?",
                (talk_id, current_id, cutoff, max(1, min(limit, 10))),
            ).fetchall()
        return [row["customer_text"] for row in rows]

    def recent_messages(self, talk_id: str, limit: int = 5) -> list[str]:
        if not talk_id:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT customer_text FROM messages WHERE talk_id=? AND received_at>=? "
                "ORDER BY rowid DESC LIMIT ?", (talk_id, cutoff, max(1, min(limit, 10))),
            ).fetchall()
        return [row["customer_text"] for row in rows]

    def conversation(self, message_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            row = db.execute("SELECT talk_id FROM messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                return []
            rows = db.execute(
                "SELECT * FROM messages WHERE talk_id=? ORDER BY rowid DESC LIMIT ?",
                (row["talk_id"], max(1, min(limit, 100))),
            ).fetchall()
        return [self._decode(item) for item in reversed(rows)]

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        raw_suggestion = value.pop("suggestion_json")
        value["suggestion"] = json.loads(raw_suggestion) if raw_suggestion else None
        return value
