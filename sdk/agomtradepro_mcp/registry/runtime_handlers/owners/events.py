"""events runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_query_events(
    event_type: str | None = None,
    event_types: list[str] | None = None,
    correlation_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload: dict[str, Any] = {"limit": limit}
    optional_values = {
        "event_type": event_type,
        "event_types": event_types,
        "correlation_id": correlation_id,
        "since": since,
        "until": until,
    }
    payload.update({key: value for key, value in optional_values.items() if value is not None})
    return client.events.query(payload)


def _fallback_get_event_metrics() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.events.metrics()


def _fallback_get_event_bus_status() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.events.status()


def _internal_handler_events_publish_event(
    event_type: str,
    payload: dict[str, Any],
    occurred_at: str,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime

    from agomtradepro import AgomTradeProClient

    allowed_event_types = {
        "regime_changed",
        "regime_confidence_low",
        "regime_distribution_shift",
        "policy_level_changed",
        "policy_event_created",
        "policy_event_updated",
        "signal_created",
        "signal_approved",
        "signal_rejected",
        "signal_triggered",
        "signal_invalidated",
        "signal_expired",
        "alpha_trigger_activated",
        "alpha_trigger_fired",
        "alpha_trigger_invalidated",
        "alpha_trigger_expired",
        "beta_gate_evaluated",
        "beta_gate_passed",
        "beta_gate_blocked",
        "decision_requested",
        "decision_approved",
        "decision_rejected",
        "decision_executed",
        "decision_execution_failed",
        "quota_exceeded",
        "quota_reset",
        "position_opened",
        "position_closed",
        "position_stopped",
        "position_adjusted",
        "stop_loss_triggered",
        "take_profit_triggered",
        "system_error",
        "audit_completed",
        "backtest_completed",
    }
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type not in allowed_event_types:
        raise ValueError("event_type is not a supported canonical domain event type")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object when provided")

    normalized_event_id = str(idempotency_key or "").strip()
    if not normalized_event_id:
        raise ValueError("idempotency_key is required")
    if len(normalized_event_id) > 64:
        raise ValueError("idempotency_key must not exceed 64 characters")

    normalized_occurred_at = str(occurred_at or "").strip()
    try:
        parsed_occurred_at = datetime.fromisoformat(normalized_occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be a valid ISO 8601 datetime") from exc
    if parsed_occurred_at.tzinfo is None or parsed_occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone offset")
    normalized_occurred_at = parsed_occurred_at.isoformat()

    def _normalize_optional_identifier(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{field_name} must be non-empty when provided")
        if len(normalized) > 64:
            raise ValueError(f"{field_name} must not exceed 64 characters")
        return normalized

    normalized_correlation_id = _normalize_optional_identifier(
        correlation_id,
        "correlation_id",
    )
    normalized_causation_id = _normalize_optional_identifier(
        causation_id,
        "causation_id",
    )
    normalized_metadata = dict(metadata or {})

    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "event_summary": {
                "event_id": normalized_event_id,
                "event_type": normalized_event_type,
                "occurred_at": normalized_occurred_at,
                "payload_keys": sorted(str(key) for key in payload),
                "metadata_keys": sorted(str(key) for key in normalized_metadata),
                "correlation_id": normalized_correlation_id,
                "causation_id": normalized_causation_id,
            },
            "side_effects": {
                "persists_stored_event": True,
                "notifies_subscribers_synchronously": True,
                "subscriber_side_effect_scope": "subscriber_defined_cross_module_writes",
                "duplicate_event_id_blocked": True,
            },
            "summary": {
                "event_id": normalized_event_id,
                "event_type": normalized_event_type,
                "payload_key_count": len(payload),
            },
            "message": (
                "Preview generated. Confirm to persist the event and synchronously notify "
                "subscribers; subscriber-defined cross-module writes may occur."
            ),
        }

    client = AgomTradeProClient()
    return client.events.publish_event(
        event_type=normalized_event_type,
        payload=dict(payload),
        metadata=normalized_metadata,
        occurred_at=normalized_occurred_at,
        event_id=normalized_event_id,
        correlation_id=normalized_correlation_id,
        causation_id=normalized_causation_id,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "query_events": _fallback_query_events,
    "get_event_metrics": _fallback_get_event_metrics,
    "get_event_bus_status": _fallback_get_event_bus_status,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "events_publish_event": _internal_handler_events_publish_event,
}
