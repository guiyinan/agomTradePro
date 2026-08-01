"""Capability-level provider health projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.numeric import safe_float


def _parse_aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _safe_nonnegative_int(value: object) -> int:
    parsed = safe_float(value, default=0.0)
    if parsed < 0 or not parsed.is_integer():
        return 0
    return int(parsed)


def build_capability_health_payload(
    snapshot: dict[str, Any],
    extra_config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge persisted capability evidence and fail closed when success is stale."""

    current_now = (now or datetime.now(UTC)).astimezone(UTC)
    capability = str(snapshot.get("capability") or "")
    health_metrics = extra_config.get("health_metrics") or {}
    metric = (
        dict(health_metrics.get(capability) or {})
        if isinstance(health_metrics, dict) and capability != "N/A"
        else {}
    )
    enriched = dict(snapshot)
    last_success_at = _parse_aware_datetime(
        enriched.get("last_success_at")
        or metric.get("last_success_at")
        or extra_config.get("provider_last_success_at")
    )
    max_age_by_capability = extra_config.get("health_max_age_hours") or {}
    configured_max_age = (
        max_age_by_capability.get(capability) if isinstance(max_age_by_capability, dict) else None
    )
    try:
        max_age_hours = float(configured_max_age or 24.0)
    except (TypeError, ValueError):
        max_age_hours = 24.0
    if max_age_hours <= 0:
        max_age_hours = 24.0

    consecutive_failures = _safe_nonnegative_int(
        enriched.get("consecutive_failures") or metric.get("consecutive_failures") or 0
    )
    age_hours = (
        max((current_now - last_success_at).total_seconds() / 3600, 0.0)
        if last_success_at is not None
        else None
    )
    block_reason_code = ""
    status = str(enriched.get("status") or "unknown")
    if last_success_at is None:
        status = "unhealthy"
        block_reason_code = "provider_capability_never_succeeded"
    elif age_hours is not None and age_hours > max_age_hours:
        status = "stale"
        block_reason_code = "provider_capability_success_stale"
    elif consecutive_failures > 0 or metric.get("last_status") == "degraded":
        status = "degraded"
        block_reason_code = "provider_capability_recent_failure"

    enriched.update(
        {
            "status": status,
            "last_success_at": last_success_at,
            "consecutive_failures": consecutive_failures,
            "max_age_hours": max_age_hours,
            "success_age_hours": round(age_hours, 3) if age_hours is not None else None,
            "must_not_use_for_decision": bool(block_reason_code),
            "block_reason_code": block_reason_code,
        }
    )
    return enriched
