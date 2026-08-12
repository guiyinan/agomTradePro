"""Current Agent/QMT connection projection with source-time preservation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from apps.broker_execution.domain.connection_freshness import (
    HEARTBEAT_FRESHNESS,
    heartbeat_times_are_fresh,
)


def _aware_time(value: object) -> datetime | None:
    """Parse one aware ISO timestamp without inventing a replacement clock."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    """Return canonical UTC text for one trusted timestamp."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def project_connection_status(
    row: Mapping[str, object],
    *,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Derive effective connection health from source and receipt clocks."""

    if evaluated_at.tzinfo is None:
        raise ValueError("connection evaluated_at must be timezone-aware")
    evaluated_utc = evaluated_at.astimezone(UTC)
    source_observed_at = _aware_time(row.get("source_observed_at"))
    received_at = _aware_time(row.get("received_at"))
    reported_status = str(row.get("status") or "")
    reported_qmt_connected = bool(row.get("reported_qmt_connected", row.get("qmt_connected")))
    is_active = bool(row.get("is_active"))
    blockers: list[str] = []
    freshness_status = "fresh"
    valid_until: datetime | None = None

    if source_observed_at is None:
        freshness_status = "missing_source"
        blockers.append("broker_agent_source_observation_missing")
    elif received_at is None:
        freshness_status = "missing_receipt"
        blockers.append("broker_agent_receipt_missing")
    elif source_observed_at > received_at or source_observed_at > evaluated_utc:
        freshness_status = "invalid_future"
        blockers.append("broker_agent_source_observation_future")
    else:
        valid_until = min(source_observed_at, received_at) + HEARTBEAT_FRESHNESS
        if not heartbeat_times_are_fresh(
            source_observed_at=source_observed_at,
            received_at=received_at,
            evaluated_at=evaluated_utc,
        ):
            freshness_status = "stale"
            blockers.append("broker_agent_heartbeat_stale")

    if not is_active:
        blockers.append("broker_agent_inactive")
    if reported_status.lower() != "online":
        blockers.append("broker_agent_not_online")
    if not reported_qmt_connected:
        blockers.append("qmt_not_reported_connected")
    effective_qmt_connected = not blockers
    bindings = row.get("bindings")
    payload: dict[str, object] = {
        "agent_id": str(row.get("agent_id") or ""),
        "display_name": str(row.get("display_name") or ""),
        "status": reported_status,
        "reported_qmt_connected": reported_qmt_connected,
        "qmt_connected": effective_qmt_connected,
        "agent_version": str(row.get("agent_version") or ""),
        "is_active": is_active,
        "source_observed_at": (
            _utc_text(source_observed_at) if source_observed_at is not None else None
        ),
        "received_at": _utc_text(received_at) if received_at is not None else None,
        "last_heartbeat_at": _utc_text(received_at) if received_at is not None else None,
        "valid_until": _utc_text(valid_until) if valid_until is not None else None,
        "freshness_status": freshness_status,
        "heartbeat_fresh": freshness_status == "fresh",
        "blocker_codes": sorted(set(blockers)),
        "must_not_use_for_decision": not effective_qmt_connected,
        "must_not_execute": not effective_qmt_connected,
        "bindings": bindings if isinstance(bindings, list) else [],
    }
    credentials = row.get("credentials")
    if isinstance(credentials, list):
        payload["credentials"] = credentials
    return payload
