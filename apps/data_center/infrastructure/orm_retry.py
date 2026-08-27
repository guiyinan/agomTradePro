"""Small ORM retry helpers for local SQLite transient contention."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from django.db import OperationalError, close_old_connections

T = TypeVar("T")

SQLITE_LOCK_RETRY_DELAYS_SECONDS = (0.2, 0.5, 1.0)


def retry_sqlite_locked_operation(operation: Callable[[], T]) -> T:
    """Retry one ORM operation when SQLite reports a short write lock."""

    for attempt in range(len(SQLITE_LOCK_RETRY_DELAYS_SECONDS) + 1):
        try:
            return operation()
        except OperationalError as exc:
            should_retry = _is_transient_sqlite_lock(exc) and attempt < len(
                SQLITE_LOCK_RETRY_DELAYS_SECONDS
            )
            if not should_retry:
                raise
            close_old_connections()
            time.sleep(SQLITE_LOCK_RETRY_DELAYS_SECONDS[attempt])
    raise RuntimeError("unreachable sqlite lock retry state")


def retry_macro_fact_upsert(manager: Any, fact: Any) -> Any:
    """Upsert one MacroFact with SQLite lock retry for local scheduled jobs."""

    return retry_sqlite_locked_operation(
        lambda: manager.update_or_create(
            indicator_code=fact.indicator_code,
            reporting_period=fact.reporting_period,
            source=fact.source,
            revision_number=fact.revision_number,
            defaults={
                "value": fact.value,
                "unit": fact.unit,
                "published_at": fact.published_at,
                "quality": fact.quality.value,
                "fetched_at": fact.fetched_at,
                "extra": fact.extra,
                "ingested_run_id": fact.ingested_run_id or None,
            },
        )
    )


def _is_transient_sqlite_lock(exc: OperationalError) -> bool:
    message = str(exc).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database schema is locked" in message
    )
