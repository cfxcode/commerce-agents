"""Tenant- and environment-scoped SQLite sidecars and append-only audit events."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import digest, uid


class Store:
    def __init__(self, path: str = ":memory:", *, environment_id: str | None = None):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.environment_id = environment_id or uid("env")
        self.db = sqlite3.connect(path, check_same_thread=False)
        if path != ":memory:":
            os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records (
              environment_id TEXT NOT NULL, merchant_id TEXT NOT NULL,
              kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
              PRIMARY KEY(environment_id, merchant_id, kind, id));
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, environment_id TEXT NOT NULL,
              merchant_id TEXT NOT NULL, task_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_events
              ON events(environment_id,merchant_id,task_id,sequence);
            PRAGMA user_version=1;
        """)

    def put(self, kind: str, merchant: str, key: str, value: Any) -> None:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if value.get("merchant_id", merchant) != merchant:
            raise ValueError("TENANT_SCOPE_MISMATCH")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)",
                (
                    self.environment_id,
                    merchant,
                    kind,
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                ),
            )

    def get(self, kind: str, merchant: str, key: str) -> dict | None:
        row = self.db.execute(
            "SELECT payload FROM records WHERE environment_id=? AND "
            "merchant_id=? AND kind=? AND id=?",
            (self.environment_id, merchant, kind, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str, merchant: str) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT payload FROM records WHERE environment_id=? AND merchant_id=? AND kind=? ORDER BY rowid",
                (self.environment_id, merchant, kind),
            )
        ]

    def delete(self, kind: str, merchant: str, key: str) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM records WHERE environment_id=? AND merchant_id=? AND kind=? AND id=?",
                (self.environment_id, merchant, kind, key),
            )

    def event(self, task: Any, event_type: str, timestamp: Any, **data: Any) -> dict:
        event = {
            "event_id": uid("event"),
            "event_type": event_type,
            "environment_id": self.environment_id,
            "task_id": task.task_id,
            "turn_id": task.turn_id,
            "merchant_id": task.merchant_id,
            "session_hash": task.session_hash,
            "timestamp": timestamp.isoformat(),
            "release_id": task.release_id,
            "knowledge_hash": task.knowledge_hash,
            **data,
        }
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO events(environment_id,merchant_id,task_id,payload) VALUES (?,?,?,?)",
                (
                    self.environment_id,
                    task.merchant_id,
                    task.task_id,
                    json.dumps(event, ensure_ascii=False, default=str),
                ),
            )
        event["sequence"] = cursor.lastrowid
        return event

    def events(
        self, merchant: str, task_id: str, after: int = 0, limit: int = 200, *, latest: bool = False
    ) -> list[dict]:
        rows = self.db.execute(
            "SELECT sequence,payload FROM events WHERE environment_id=? AND merchant_id=? AND task_id=? AND sequence>? ORDER BY sequence "
            + ("DESC" if latest else "ASC")
            + " LIMIT ?",
            (self.environment_id, merchant, task_id, after, min(limit, 1000)),
        )
        result = [json.loads(row["payload"]) | {"sequence": row["sequence"]} for row in rows]
        return list(reversed(result)) if latest else result

    @staticmethod
    def session_key(session: Any) -> str:
        return digest([session.merchant_id, session.session_id])

    def close(self) -> None:
        self.db.close()
