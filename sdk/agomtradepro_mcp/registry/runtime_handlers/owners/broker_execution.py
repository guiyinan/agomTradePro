"""broker_execution runtime handlers backed only by the formal SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_ORDER_DETAIL_SCALAR_FIELDS = (
    "client_order_id",
    "account_id",
    "agent_id",
    "asset_code",
    "market",
    "side",
    "order_type",
    "quantity",
    "limit_price",
    "estimated_amount",
    "status",
    "source_recommendation_ids",
    "source_signal_ids",
    "risk_policy_version",
    "approval_mode",
    "approval_digest",
    "approved_by",
    "approved_at",
    "expires_at",
    "submitted_at",
    "broker_order_id",
    "filled_quantity",
    "average_fill_price",
    "failure_code",
    "failure_message",
    "version",
    "created_at",
    "updated_at",
    "evaluated_at",
    "transport_blocker_codes",
    "event_payload_policy",
    "risk_snapshot_policy",
    "risk_snapshot_content_hash",
    "approval_evidence_status",
    "approval_evidence_blocker_codes",
    "permission",
    "must_not_use_for_decision",
    "must_not_execute",
)
_ACTION_FIELDS = ("approve", "reject", "cancel")
_EVENT_FIELDS = ("event_id", "event_type", "status", "occurred_at", "received_at")
_FILL_FIELDS = ("broker_trade_id", "quantity", "price", "amount", "occurred_at")
_EVIDENCE_FIELDS = (
    "output_owner",
    "output_artifact_type",
    "output_artifact_id",
    "output_artifact_version",
    "output_content_hash",
    "envelope_content_hash",
    "operator_spec_content_hash",
    "claim_kind",
    "method_kind",
    "research_family",
    "governance_state",
    "permission",
    "blocker_codes",
    "dependency_flags",
    "track_record_availability",
    "track_record_content_hash",
    "n_eff",
    "coverage",
    "evaluated_at",
    "valid_until",
    "must_not_use_for_decision",
    "must_not_execute",
)


def _closed_projection(value: object, fields: tuple[str, ...], *, label: str) -> dict[str, Any]:
    """Copy an exact allowlist from one trusted mapping."""

    if not isinstance(value, Mapping):
        raise ValueError(f"Broker order detail {label} must be an object")
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"Broker order detail {label} is missing fields: {missing}")
    return {field: value[field] for field in fields}


def _closed_rows(value: object, fields: tuple[str, ...], *, label: str) -> list[dict[str, Any]]:
    """Copy bounded timeline rows without forwarding arbitrary nested payloads."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"Broker order detail {label} must be an array")
    return [_closed_projection(row, fields, label=label) for row in value]


def _mcp_order_detail_projection(value: object) -> dict[str, Any]:
    """Publish only the exact Broker order-detail MCP contract."""

    result = _closed_projection(value, _ORDER_DETAIL_SCALAR_FIELDS, label="response")
    source = value
    assert isinstance(source, Mapping)
    result["events"] = _closed_rows(source.get("events"), _EVENT_FIELDS, label="events")
    result["fills"] = _closed_rows(source.get("fills"), _FILL_FIELDS, label="fills")
    result["lifecycle_transitions"] = _closed_projection(
        source.get("lifecycle_transitions"), _ACTION_FIELDS, label="lifecycle_transitions"
    )
    result["actor_authorization"] = _closed_projection(
        source.get("actor_authorization"), _ACTION_FIELDS, label="actor_authorization"
    )
    evidence = source.get("approval_evidence")
    result["approval_evidence"] = (
        None
        if evidence is None
        else _closed_projection(evidence, _EVIDENCE_FIELDS, label="approval_evidence")
    )
    return result


def _client():
    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient()


def _internal_handler_broker_execution_overview() -> dict[str, Any]:
    return _client().broker_execution.overview()


def _internal_handler_broker_execution_orders(
    account_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return _client().broker_execution.list_orders(account_id=account_id, status=status, limit=limit)


def _internal_handler_broker_execution_order(client_order_id: str) -> dict[str, Any]:
    return _mcp_order_detail_projection(_client().broker_execution.get_order(client_order_id))


def _internal_handler_broker_execution_connections() -> dict[str, Any]:
    return _client().broker_execution.connections()


def _internal_handler_broker_execution_reconciliations(limit: int = 100) -> dict[str, Any]:
    return _client().broker_execution.reconciliations(limit=limit)


def _internal_handler_broker_execution_audit(limit: int = 100) -> dict[str, Any]:
    return _client().broker_execution.audit(limit=limit)


def _order_action(
    *,
    action: str,
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.order_action(
        client_order_id,
        action,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_approve(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="approve",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_reject(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="reject",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_cancel(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="cancel",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_kill_switch(
    account_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.set_kill_switch(
        account_id=account_id,
        active=True,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_resume(
    account_id: int,
    reason: str,
    reauth_password: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.set_kill_switch(
        account_id=account_id,
        active=False,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
        reauth_password=reauth_password if not preview_only else None,
    )


def _internal_handler_broker_execution_resolve(
    run_id: int,
    resolution: str,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.resolve_reconciliation(
        run_id,
        resolution=resolution,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Any] = {}

GOVERNED_HANDLERS = {
    "get_broker_execution_overview": _internal_handler_broker_execution_overview,
    "list_broker_execution_orders": _internal_handler_broker_execution_orders,
    "get_broker_execution_order": _internal_handler_broker_execution_order,
    "get_broker_execution_connections": _internal_handler_broker_execution_connections,
    "list_broker_execution_reconciliations": _internal_handler_broker_execution_reconciliations,
    "list_broker_execution_audit": _internal_handler_broker_execution_audit,
    "broker_execution_approve_order": _internal_handler_broker_execution_approve,
    "broker_execution_reject_order": _internal_handler_broker_execution_reject,
    "broker_execution_request_cancel": _internal_handler_broker_execution_cancel,
    "broker_execution_trigger_kill_switch": _internal_handler_broker_execution_kill_switch,
    "broker_execution_resume_trading": _internal_handler_broker_execution_resume,
    "broker_execution_resolve_reconciliation": _internal_handler_broker_execution_resolve,
}
