"""In-memory server log buffer for admin live viewing/export."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
import logging
import os

_MAX_ENTRIES = max(100, int(os.getenv("ADMIN_LOG_BUFFER_SIZE", "5000")))
_BUFFER = deque(maxlen=_MAX_ENTRIES)
_LOCK = Lock()
_SEQ = 0


def append_record(record: logging.LogRecord, formatted_message: str) -> int:
    """Append a log record snapshot and return its sequence id."""
    global _SEQ
    with _LOCK:
        _SEQ += 1
        _BUFFER.append(
            {
                "id": _SEQ,
                "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": formatted_message,
            }
        )
        return _SEQ


def get_entries(since_id: int = 0, limit: int = 200) -> tuple[list[dict], int]:
    """Return entries with id > since_id and the latest cursor id."""
    since_id = max(0, int(since_id))
    limit = max(1, min(int(limit), 2000))
    with _LOCK:
        rows = [row for row in _BUFFER if row["id"] > since_id]
        if len(rows) > limit:
            rows = rows[-limit:]
        last_id = _BUFFER[-1]["id"] if _BUFFER else since_id
    return rows, last_id


def dump_as_text() -> str:
    """Export all currently buffered logs to plain text."""
    with _LOCK:
        rows = list(_BUFFER)
    lines = [f"{r['ts']} [{r['level']}] {r['logger']} | {r['message']}" for r in rows]
    return "\n".join(lines) + ("\n" if lines else "")
