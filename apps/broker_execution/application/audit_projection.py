"""Typed, bounded, and fail-closed broker execution audit projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final


@dataclass(frozen=True, slots=True)
class _TextSpec:
    max_length: int = 256


@dataclass(frozen=True, slots=True)
class _ListSpec:
    item_kind: str
    max_items: int = 50


_TEXT: Final = _TextSpec()
_LONG_TEXT: Final = _TextSpec(max_length=1000)
_INT: Final = "int"
_BOOL: Final = "bool"
_TEXT_LIST: Final = _ListSpec("text")
_INT_LIST: Final = _ListSpec("int")
_MAX_DEPTH: Final = 3
_SENSITIVE_KEY_PARTS: Final = (
    "actor",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "nonce",
    "password",
    "secret",
    "signature",
    "source_ip",
    "token",
    "user_agent",
)

_ORDER_SCHEMA: Final[dict[str, object]] = {
    "status": _TEXT,
    "submitted_at": _TEXT,
    "filled_quantity": _TEXT,
    "average_fill_price": _TEXT,
    "failure_code": _TEXT,
    "version": _INT,
    "updated_at": _TEXT,
}

_STATIC_SCHEMAS: Final[dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]]] = {
    ("login_failed", "user_authentication"): ({}, {}),
    ("permission_denied", "broker_execution_action"): (
        {},
        {},
    ),
    ("agent_auth_failed", "agent_authentication"): (
        {},
        {},
    ),
    ("create_live_order", "live_order"): ({}, _ORDER_SCHEMA),
    ("order_risk_rejected", "live_order"): ({}, _ORDER_SCHEMA),
    ("order_approve", "live_order"): (_ORDER_SCHEMA, _ORDER_SCHEMA),
    ("order_reject", "live_order"): (_ORDER_SCHEMA, _ORDER_SCHEMA),
    ("order_cancel", "live_order"): (_ORDER_SCHEMA, _ORDER_SCHEMA),
    ("kill_switch_on", "trading_control"): (
        {"kill_switch_active": _BOOL},
        {
            "kill_switch_active": _BOOL,
            "changed_at": _TEXT,
        },
    ),
    ("kill_switch_off", "trading_control"): (
        {"kill_switch_active": _BOOL},
        {
            "kill_switch_active": _BOOL,
            "changed_at": _TEXT,
        },
    ),
    ("binding_upserted", "broker_account_binding"): (
        {
            "account_type": _TEXT,
            "is_active": _BOOL,
        },
        {
            "account_type": _TEXT,
            "is_active": _BOOL,
        },
    ),
    ("account_access_updated", "broker_account_access"): (
        {
            "can_approve": _BOOL,
            "can_trade": _BOOL,
            "is_active": _BOOL,
        },
        {
            "can_approve": _BOOL,
            "can_trade": _BOOL,
            "is_active": _BOOL,
        },
    ),
    ("agent_credential_rotated", "agent_credential"): (
        {},
        {
            "expires_at": _TEXT,
        },
    ),
    ("agent_credential_revoked", "agent_credential"): (
        {},
        {"revoked_at": _TEXT},
    ),
    ("agent_full_sync_requested", "broker_agent"): (
        {},
        {"command_type": _TEXT},
    ),
    ("execution_settings_updated", "broker_account_binding"): (
        {
            "auto_execution_enabled": _BOOL,
            "max_single_order_amount": _TEXT,
            "daily_order_amount_limit": _TEXT,
            "allowed_symbols": _TEXT_LIST,
            "max_position_count": _INT,
            "max_snapshot_age_seconds": _INT,
            "price_deviation_limit_pct": _TEXT,
            "allowed_trading_windows": _TEXT_LIST,
            "enforce_trading_session": _BOOL,
        },
        {
            "auto_execution_enabled": _BOOL,
            "enforce_trading_session": _BOOL,
        },
    ),
    ("resolve_reconciliation", "reconciliation_run"): (
        {
            "status": _TEXT,
            "summary": {
                "difference_count": _INT,
                "p0_auto_stop": _BOOL,
                "resolution": _TEXT,
                "snapshot_captured_at": _TEXT,
            },
        },
        {
            "status": _TEXT,
            "summary": {
                "difference_count": _INT,
                "p0_auto_stop": _BOOL,
                "resolution": _TEXT,
                "snapshot_captured_at": _TEXT,
            },
        },
    ),
}

_COMMAND_SCHEMAS: Final[dict[tuple[str, str], tuple[dict[str, object], dict[str, object]]]] = {
    (action, resource_type): (
        {"status": _TEXT},
        {
            "status": _TEXT,
            "command_status": _TEXT,
            "awaiting_broker_final_status": _BOOL,
        },
    )
    for action, resource_type in (
        ("agent_command_cancel_completed", "broker_command"),
        ("agent_command_cancel_completed", "live_order"),
        ("agent_command_cancel_failed", "broker_command"),
        ("agent_command_cancel_failed", "live_order"),
        ("agent_command_full_sync_completed", "broker_command"),
        ("agent_command_full_sync_failed", "broker_command"),
    )
}


@dataclass(frozen=True, slots=True)
class BrokerAuditEventProjection:
    """One display-only audit event with explicitly projected details."""

    payload: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        """Return a detached JSON-compatible response payload."""

        return dict(self.payload)


def _is_sensitive_key(value: object) -> bool:
    normalized = str(value).strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _bounded_text(value: object, max_length: int) -> tuple[str | None, bool]:
    if not isinstance(value, str):
        return None, True
    normalized = value.strip()
    if len(normalized) > max_length:
        return normalized[:max_length], True
    return normalized, False


def _project_value(value: object, spec: object, *, depth: int) -> tuple[object | None, bool]:
    if value is None:
        return None, False
    if isinstance(spec, _TextSpec):
        return _bounded_text(value, spec.max_length)
    if spec == _BOOL:
        return (value, False) if isinstance(value, bool) else (None, True)
    if spec == _INT:
        return (
            (value, False)
            if isinstance(value, int) and not isinstance(value, bool)
            else (None, True)
        )
    if isinstance(spec, _ListSpec):
        if not isinstance(value, (list, tuple)):
            return None, True
        projected: list[object] = []
        redacted = len(value) > spec.max_items
        item_spec: object = _TEXT if spec.item_kind == "text" else _INT
        for item in value[: spec.max_items]:
            safe_item, item_redacted = _project_value(item, item_spec, depth=depth + 1)
            redacted = redacted or item_redacted
            if safe_item is not None:
                projected.append(safe_item)
        return projected, redacted
    if isinstance(spec, Mapping):
        if not isinstance(value, Mapping) or depth >= _MAX_DEPTH:
            return None, True
        return _project_mapping(value, spec, depth=depth + 1)
    return None, True


def _project_mapping(
    raw: Mapping[object, object],
    schema: Mapping[str, object],
    *,
    depth: int = 0,
) -> tuple[dict[str, object], bool]:
    projected: dict[str, object] = {}
    redacted = False
    for key, value in raw.items():
        normalized_key = str(key)
        if _is_sensitive_key(normalized_key) or normalized_key not in schema:
            redacted = True
            continue
        safe_value, value_redacted = _project_value(
            value,
            schema[normalized_key],
            depth=depth,
        )
        redacted = redacted or value_redacted
        if safe_value is not None:
            projected[normalized_key] = safe_value
    return projected, redacted


def _aware_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _event_schemas(
    action: str,
    resource_type: str,
) -> tuple[dict[str, object], dict[str, object]] | None:
    static = _STATIC_SCHEMAS.get((action, resource_type))
    if static is not None:
        return static
    return _COMMAND_SCHEMAS.get((action, resource_type))


def project_broker_audit_event(
    raw: Mapping[str, object],
    *,
    evaluated_at: datetime,
) -> BrokerAuditEventProjection:
    """Project one persisted audit row through exact, fail-closed allowlists."""

    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    evaluated = evaluated_at.astimezone(UTC)
    action, action_redacted = _bounded_text(raw.get("action"), 128)
    resource_type, resource_redacted = _bounded_text(raw.get("resource_type"), 128)
    normalized_action = action or ""
    normalized_resource = resource_type or ""
    blockers: set[str] = set()
    if action_redacted or resource_redacted:
        blockers.add("broker_audit_metadata_invalid")

    created = _aware_created_at(raw.get("created_at"))
    if created is None:
        blockers.add("broker_audit_created_at_invalid")
    elif created > evaluated:
        blockers.add("broker_audit_created_at_future")

    schemas = _event_schemas(normalized_action, normalized_resource)
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    details_redacted = False
    if schemas is None:
        blockers.add("broker_audit_action_resource_unrecognized")
        details_redacted = True
    else:
        raw_before = raw.get("before")
        raw_after = raw.get("after")
        if not isinstance(raw_before, Mapping) or not isinstance(raw_after, Mapping):
            blockers.add("broker_audit_details_invalid")
            details_redacted = True
        else:
            before, before_redacted = _project_mapping(raw_before, schemas[0])
            after, after_redacted = _project_mapping(raw_after, schemas[1])
            details_redacted = before_redacted or after_redacted

    if details_redacted:
        blockers.add("broker_audit_details_redacted")

    event_id = raw.get("id")
    account_id = raw.get("account_id")
    payload: dict[str, object] = {
        "id": event_id if isinstance(event_id, int) and not isinstance(event_id, bool) else None,
        "actor_type": (_bounded_text(raw.get("actor_type", ""), 32)[0] or "unknown"),
        "action": normalized_action,
        "account_id": (
            account_id if isinstance(account_id, int) and not isinstance(account_id, bool) else None
        ),
        "resource_type": normalized_resource,
        "created_at": created.isoformat() if created is not None else None,
        "evaluated_at": evaluated.isoformat(),
        "before": before,
        "after": after,
        "details_redacted": details_redacted,
        "blocker_codes": sorted(blockers),
        "permission": "display_only",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    return BrokerAuditEventProjection(payload=payload)
