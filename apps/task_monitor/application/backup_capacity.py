"""Application policy for database-backup capacity preflight."""

from __future__ import annotations

from django.conf import settings

from core.integration.config_center_runtime import (
    collect_storage_capacity_profile,
    evaluate_storage_pressure,
)

BLOCKING_BACKUP_PRESSURE_STATES = frozenset({"blocked", "critical", "emergency"})


def _required_nonnegative_int(payload: dict[str, object], key: str) -> int:
    """Narrow one owner payload field before using it in capacity arithmetic."""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"capacity_payload_{key}_invalid")
    return value


def collect_backup_capacity_report() -> dict[str, object]:
    """Collect capacity and reserve one database-sized local backup peak."""

    environment = "development" if settings.DEBUG else "production"
    observation = collect_storage_capacity_profile(
        environment=environment,
        source="database-backup-preflight",
    )
    filesystem_used_bytes = _required_nonnegative_int(
        observation,
        "filesystem_used_bytes",
    )
    database_size_bytes = _required_nonnegative_int(observation, "database_size_bytes")
    filesystem_total_bytes = _required_nonnegative_int(
        observation,
        "filesystem_total_bytes",
    )
    projected_used_bytes = filesystem_used_bytes + database_size_bytes
    report = evaluate_storage_pressure(
        used_bytes=projected_used_bytes,
        actual_capacity_bytes=filesystem_total_bytes,
    )
    return {
        **report,
        "observation_id": str(observation["observation_id"]),
        "database_size_bytes": database_size_bytes,
        "projected_used_bytes": projected_used_bytes,
    }


def require_backup_capacity() -> dict[str, object]:
    """Return capacity evidence or block every backup-producing entrypoint."""

    report = collect_backup_capacity_report()
    state = str(report.get("state", "blocked"))
    if state in BLOCKING_BACKUP_PRESSURE_STATES:
        reason = str(report.get("reason", "storage_pressure_blocked"))
        raise RuntimeError(reason)
    return report


__all__ = [
    "BLOCKING_BACKUP_PRESSURE_STATES",
    "collect_backup_capacity_report",
    "require_backup_capacity",
]
