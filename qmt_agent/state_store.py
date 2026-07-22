"""Crash-safe local idempotency and submission recovery state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class AgentStateStore:
    """SQLite store recording orders before the irreversible broker call."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                client_order_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                broker_order_id TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def get(self, client_order_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT status, broker_order_id, payload FROM submissions WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "broker_order_id": row[1], "payload": json.loads(row[2])}

    def mark_submitting(self, client_order_id: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO submissions(client_order_id,status,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
            (client_order_id, "SUBMITTING", json.dumps(payload, ensure_ascii=False)),
        )
        self.connection.commit()

    def mark_result(self, client_order_id: str, status: str, broker_order_id: str = "") -> None:
        self.connection.execute(
            "UPDATE submissions SET status=?,broker_order_id=?,updated_at=CURRENT_TIMESTAMP WHERE client_order_id=?",
            (status, broker_order_id, client_order_id),
        )
        self.connection.commit()

    def unresolved(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT client_order_id,status,broker_order_id,payload FROM submissions WHERE status IN ('SUBMITTING','RECONCILIATION_REQUIRED')"
        ).fetchall()
        return [
            {
                "client_order_id": row[0],
                "status": row[1],
                "broker_order_id": row[2],
                "payload": json.loads(row[3]),
            }
            for row in rows
        ]

    def close(self) -> None:
        self.connection.close()
