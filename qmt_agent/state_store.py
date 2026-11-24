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
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                client_order_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                broker_order_id TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS submission_reports (event_id TEXT PRIMARY KEY, event TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS agent_controls (name TEXT PRIMARY KEY, active INTEGER NOT NULL)"
        )
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS submission_confirmations (
                client_order_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                status TEXT NOT NULL, broker_order_id TEXT NOT NULL
            )
            """)
        self.connection.execute("""
            CREATE VIEW IF NOT EXISTS effective_submissions AS
            SELECT s.client_order_id, COALESCE(c.status, s.status) AS status,
                   COALESCE(c.broker_order_id, s.broker_order_id) AS broker_order_id, s.payload
            FROM submissions s LEFT JOIN submission_confirmations c USING(client_order_id)
            """)
        self.connection.commit()

    def get(self, client_order_id: str) -> dict[str, Any] | None:
        """Read the latest confirmed state or the original local submission outcome."""

        row = self.connection.execute(
            "SELECT status, broker_order_id, payload FROM effective_submissions WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "broker_order_id": row[1], "payload": json.loads(row[2])}

    def mark_submitting(self, client_order_id: str, payload: dict[str, Any]) -> None:
        """Reserve a client ID exactly once across processes before any broker call."""
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO submissions(client_order_id,status,payload) VALUES(?,?,?) "
                "ON CONFLICT(client_order_id) DO NOTHING",
                (client_order_id, "SUBMITTING", json.dumps(payload, ensure_ascii=False)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Order already exists in the local idempotency store")

    def mark_result(
        self,
        client_order_id: str,
        status: str,
        broker_order_id: str = "",
        *,
        event: dict[str, Any] | None = None,
        from_unresolved: bool = False,
    ) -> None:
        """Persist the state and its unacknowledged original report in one transaction."""
        with self.connection:
            update = "UPDATE submissions SET status=?,broker_order_id=?,updated_at=CURRENT_TIMESTAMP WHERE client_order_id=?"
            if from_unresolved:
                update += (
                    " AND (SELECT e.status FROM effective_submissions e"
                    " WHERE e.client_order_id = submissions.client_order_id)"
                    " IN ('SUBMITTING','RECONCILIATION_REQUIRED')"
                )
            cursor = self.connection.execute(
                update,
                (status, broker_order_id, client_order_id),
            )
            if cursor.rowcount != 1:
                if from_unresolved:
                    return
                raise RuntimeError("Submission result has no local reservation")
            if event is not None:
                self.connection.execute(
                    "INSERT INTO submission_reports(event_id,event) VALUES(?,?) ON CONFLICT(event_id) DO NOTHING",
                    (event["event_id"], json.dumps(event, ensure_ascii=False, allow_nan=False)),
                )

    def pending_reports(self) -> list[dict[str, Any]]:
        """Return one bounded batch of original submission events in local sequence."""
        return [
            json.loads(row[0])
            for row in self.connection.execute(
                "SELECT event FROM submission_reports ORDER BY rowid LIMIT 200"
            )
        ]

    def acknowledge_reports(self, events: list[dict[str, Any]]) -> None:
        """Remove only original events whose upload the server acknowledged."""
        with self.connection:
            self.connection.executemany(
                "DELETE FROM submission_reports WHERE event_id=?",
                [(event["event_id"],) for event in events],
            )

    def observe_order_states(self, states: object, reported_ids: set[str]) -> None:
        """Mirror versioned server projections only for locally reserved orders in this batch."""

        if not isinstance(states, list):
            return
        with self.connection:
            for row in states:
                if not isinstance(row, dict):
                    continue
                client_id = row.get("client_order_id")
                version = row.get("version")
                status = row.get("status")
                broker_id = row.get("broker_order_id")
                if (
                    not isinstance(client_id, str)
                    or client_id not in reported_ids
                    or type(version) is not int
                    or not 0 < version <= 2**63 - 1
                    or not isinstance(status, str)
                    or not status
                    or not isinstance(broker_id, str)
                ):
                    continue
                self.connection.execute(
                    """
                    INSERT INTO submission_confirmations(client_order_id,version,status,broker_order_id)
                    SELECT client_order_id, ?, ?, ? FROM submissions WHERE client_order_id = ?
                    ON CONFLICT(client_order_id) DO UPDATE SET
                        version=excluded.version, status=excluded.status, broker_order_id=excluded.broker_order_id
                    WHERE excluded.version > submission_confirmations.version
                    """,
                    (version, status, broker_id, client_id),
                )

    def is_paused(self) -> bool:
        """Read the persisted manual pause, including one set by another local process."""
        row = self.connection.execute(
            "SELECT active FROM agent_controls WHERE name='paused'"
        ).fetchone()
        return bool(row and row[0])

    def set_paused(self, paused: bool) -> None:
        """Persist an explicit pause or resume before acknowledging the command."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO agent_controls(name,active) VALUES('paused',?) "
                "ON CONFLICT(name) DO UPDATE SET active=excluded.active",
                (int(paused),),
            )

    def unresolved(self) -> list[dict[str, Any]]:
        """Return reservations whose latest known state still requires a broker query."""

        rows = self.connection.execute(
            "SELECT client_order_id,status,broker_order_id,payload FROM effective_submissions WHERE status IN ('SUBMITTING','RECONCILIATION_REQUIRED')"
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
