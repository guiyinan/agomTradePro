"""Fail-safe PostgreSQL connection-capacity projection for Prometheus."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import connections

from core.metrics import (
    record_database_connection_observation_failure,
    record_database_connection_snapshot,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DatabaseConnectionSnapshot:
    """One bounded observation of PostgreSQL backend usage and capacity."""

    active: int
    idle: int
    other: int
    max_connections: int
    reserved_connections: int

    @property
    def usable_connections(self) -> int:
        """Return client capacity available outside PostgreSQL reserved slots."""

        return self.max_connections - self.reserved_connections


def _non_negative_integer(value: object, *, field_name: str) -> int:
    """Narrow one PostgreSQL scalar to a non-negative integer."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be an integer")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return normalized


def _read_postgresql_connection_snapshot(using: str) -> DatabaseConnectionSnapshot:
    """Read one aggregate snapshot from PostgreSQL system catalogs."""

    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE state = 'active'),
                COUNT(*) FILTER (WHERE state = 'idle'),
                COUNT(*) FILTER (
                    WHERE state IS NULL OR state NOT IN ('active', 'idle')
                ),
                current_setting('max_connections')::integer,
                current_setting('superuser_reserved_connections')::integer
                + COALESCE(
                    current_setting('reserved_connections', true),
                    '0'
                )::integer
            FROM pg_stat_activity
            WHERE backend_type = 'client backend'
            """)
        row: tuple[object, ...] | None = cursor.fetchone()

    if row is None or len(row) != 5:
        raise ValueError("PostgreSQL connection snapshot is incomplete")

    snapshot = DatabaseConnectionSnapshot(
        active=_non_negative_integer(row[0], field_name="active"),
        idle=_non_negative_integer(row[1], field_name="idle"),
        other=_non_negative_integer(row[2], field_name="other"),
        max_connections=_non_negative_integer(row[3], field_name="max_connections"),
        reserved_connections=_non_negative_integer(row[4], field_name="reserved_connections"),
    )
    if snapshot.usable_connections <= 0:
        raise ValueError("PostgreSQL usable connection capacity must be positive")
    return snapshot


def project_database_connection_metrics(using: str = "default") -> bool:
    """Publish PostgreSQL connection usage without breaking metric scrapes.

    Non-PostgreSQL local environments are intentionally skipped. Production
    observation failures publish ``database_connection_observation_up=0`` and
    log only the exception type so connection strings cannot leak.
    """

    try:
        connection = connections[using]
        if connection.vendor != "postgresql":
            return True
        snapshot = _read_postgresql_connection_snapshot(using)
        record_database_connection_snapshot(
            database=using,
            active=snapshot.active,
            idle=snapshot.idle,
            other=snapshot.other,
            max_connections=snapshot.max_connections,
            reserved_connections=snapshot.reserved_connections,
        )
        return True
    except Exception as exc:
        record_database_connection_observation_failure(database=using)
        logger.warning(
            "Failed to project database connection metrics (error_type=%s)",
            type(exc).__name__,
        )
        return False
