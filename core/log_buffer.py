"""In-memory server log buffer for admin live viewing/export."""

from __future__ import annotations

import logging
import os
import re
from collections import deque
from datetime import datetime
from threading import Lock
from typing import TypedDict


class LogEntry(TypedDict):
    """One bounded server-log snapshot exposed to administrators."""

    id: int
    ts: str
    level: str
    logger: str
    message: str


_URI_CREDENTIAL_PATTERN = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key|authorization)\b(\s*[:=]\s*)([^\s,;]+)"
)


def _buffer_size() -> int:
    """Return a safe bounded buffer size from the environment."""

    try:
        configured = int(os.getenv("ADMIN_LOG_BUFFER_SIZE", "5000"))
    except (TypeError, ValueError):
        configured = 5000
    return min(max(configured, 100), 100_000)


def _redact_message(message: str) -> str:
    """Remove common credential forms before retaining log text in memory."""

    bounded = message[:16_384]
    bounded = _URI_CREDENTIAL_PATTERN.sub(r"\1<redacted>@", bounded)
    return _SECRET_ASSIGNMENT_PATTERN.sub(r"\1\2<redacted>", bounded)


_MAX_ENTRIES = _buffer_size()
_BUFFER: deque[LogEntry] = deque(maxlen=_MAX_ENTRIES)
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
                "message": _redact_message(formatted_message),
            }
        )
        return _SEQ


def get_entries(since_id: int = 0, limit: int = 200) -> tuple[list[LogEntry], int]:
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
