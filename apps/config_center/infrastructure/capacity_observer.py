"""Read-only filesystem and database capacity observer."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.config_center.domain.runtime_config import StorageCapacityObservation


def _database_metrics() -> tuple[int, dict[str, int], dict[str, object]]:
    """Return database size, relation sizes and engine metadata."""

    vendor = connection.vendor
    metadata: dict[str, object] = {"database_vendor": vendor}
    if vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), pg_database_size(current_database())")
            database_name, database_size = cursor.fetchone()
            cursor.execute("""
                SELECT n.nspname || '.' || c.relname,
                       pg_total_relation_size(c.oid)
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'm', 'p')
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY pg_total_relation_size(c.oid) DESC
                LIMIT 100
                """)
            relation_rows = cursor.fetchall()
        metadata["database_name"] = str(database_name)
        return int(database_size), {str(name): int(size) for name, size in relation_rows}, metadata

    database_name = connection.settings_dict.get("NAME")
    database_path = Path(str(database_name)) if database_name else None
    database_size = database_path.stat().st_size if database_path and database_path.exists() else 0
    relation_sizes: dict[str, int] = {}
    if database_path and database_path.exists():
        relation_sizes[database_path.name] = int(database_size)
        wal_path = Path(f"{database_path}-wal")
        if wal_path.exists():
            relation_sizes[wal_path.name] = int(wal_path.stat().st_size)
    metadata["database_name"] = str(database_name or "")
    return int(database_size), relation_sizes, metadata


def collect_storage_capacity_observation(
    *,
    environment: str,
    policy_key: str = "",
    configured_capacity_bytes: int | None = None,
    effective_capacity_bytes: int | None = None,
    usage_ratio: float | None = None,
    pressure_state: str = "",
    source: str = "runtime-observer",
) -> StorageCapacityObservation:
    """Collect one read-only capacity snapshot from the current host/database."""

    root = Path(settings.BASE_DIR)
    usage = shutil.disk_usage(root)
    database_size, relation_sizes, metadata = _database_metrics()
    metadata.update({"observed_path": str(root), "database_size_bytes": database_size})
    return StorageCapacityObservation(
        observation_id=str(uuid4()),
        environment=environment,
        observed_at=timezone.now(),
        filesystem_total_bytes=int(usage.total),
        filesystem_used_bytes=int(usage.used),
        filesystem_free_bytes=int(usage.free),
        database_size_bytes=database_size,
        relation_sizes=relation_sizes,
        policy_key=policy_key,
        configured_capacity_bytes=configured_capacity_bytes,
        effective_capacity_bytes=effective_capacity_bytes,
        usage_ratio=usage_ratio,
        pressure_state=pressure_state,
        source=source,
        metadata=metadata,
    )


class StorageCapacityObserver:
    """Infrastructure adapter for the capacity-profile application port."""

    def collect(
        self,
        *,
        environment: str,
        policy_key: str,
        configured_capacity_bytes: int,
        source: str,
    ) -> StorageCapacityObservation:
        """Collect one read-only observation for an active storage policy."""

        return collect_storage_capacity_observation(
            environment=environment,
            policy_key=policy_key,
            configured_capacity_bytes=configured_capacity_bytes,
            source=source,
        )


__all__ = ["StorageCapacityObserver", "collect_storage_capacity_observation"]
