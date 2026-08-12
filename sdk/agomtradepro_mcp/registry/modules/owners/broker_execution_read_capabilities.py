"""broker_execution strict-read MCP capability manifests."""

from __future__ import annotations

from typing import Any

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _closed_object(properties: dict[str, Any]) -> dict[str, Any]:
    """Build one exact object schema with every listed field required."""

    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_ACTION_FLAGS_SCHEMA = _closed_object(
    {
        "approve": {"type": "boolean"},
        "reject": {"type": "boolean"},
        "cancel": {"type": "boolean"},
    }
)
_STRING_ARRAY_SCHEMA = {"type": "array", "items": {"type": "string"}}
_EVIDENCE_SUMMARY_SCHEMA = _closed_object(
    {
        "output_owner": {"type": "string"},
        "output_artifact_type": {"type": "string"},
        "output_artifact_id": {"type": "string"},
        "output_artifact_version": {"type": "string"},
        "output_content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "envelope_content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "operator_spec_content_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "claim_kind": {"type": "string", "enum": ["derived"]},
        "method_kind": {"type": "string", "enum": ["deterministic"]},
        "research_family": {"type": "string"},
        "governance_state": {"type": "string", "enum": ["legacy_unverified"]},
        "permission": {"type": "string", "enum": ["display_only"]},
        "blocker_codes": _STRING_ARRAY_SCHEMA,
        "dependency_flags": _STRING_ARRAY_SCHEMA,
        "track_record_availability": {"type": "string", "enum": ["unavailable"]},
        "track_record_content_hash": {"type": ["string", "null"]},
        "n_eff": {"type": ["string", "null"]},
        "coverage": {"type": ["string", "null"]},
        "evaluated_at": {"type": "string", "format": "date-time"},
        "valid_until": {"type": "string", "format": "date-time"},
        "must_not_use_for_decision": {"type": "boolean", "enum": [True]},
        "must_not_execute": {"type": "boolean", "enum": [True]},
    }
)
_EVENT_SCHEMA = _closed_object(
    {
        "event_id": {"type": "string"},
        "event_type": {"type": "string"},
        "status": {"type": "string"},
        "occurred_at": {"type": "string", "format": "date-time"},
        "received_at": {"type": "string", "format": "date-time"},
    }
)
_FILL_SCHEMA = _closed_object(
    {
        "broker_trade_id": {"type": "string"},
        "quantity": {"type": "string"},
        "price": {"type": "string"},
        "amount": {"type": "string"},
        "occurred_at": {"type": "string", "format": "date-time"},
    }
)
_ORDER_DETAIL_OUTPUT_SCHEMA = _closed_object(
    {
        "client_order_id": {"type": "string", "format": "uuid"},
        "account_id": {"type": "integer", "minimum": 1},
        "agent_id": {"type": ["string", "null"]},
        "asset_code": {"type": "string"},
        "market": {"type": "string"},
        "side": {"type": "string", "enum": ["BUY", "SELL"]},
        "order_type": {"type": "string"},
        "quantity": {"type": "string"},
        "limit_price": {"type": ["string", "null"]},
        "estimated_amount": {"type": "string"},
        "status": {"type": "string"},
        "source_recommendation_ids": _STRING_ARRAY_SCHEMA,
        "source_signal_ids": _STRING_ARRAY_SCHEMA,
        "risk_policy_version": {"type": "string"},
        "approval_mode": {"type": "string"},
        "approval_digest": {"type": "string"},
        "approved_by": {"type": ["integer", "null"]},
        "approved_at": {"type": ["string", "null"], "format": "date-time"},
        "expires_at": {"type": ["string", "null"], "format": "date-time"},
        "submitted_at": {"type": ["string", "null"], "format": "date-time"},
        "broker_order_id": {"type": "string"},
        "filled_quantity": {"type": "string"},
        "average_fill_price": {"type": ["string", "null"]},
        "failure_code": {"type": "string"},
        "failure_message": {"type": "string"},
        "version": {"type": "integer", "minimum": 1},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "events": {"type": "array", "items": _EVENT_SCHEMA},
        "fills": {"type": "array", "items": _FILL_SCHEMA},
        "evaluated_at": {"type": "string", "format": "date-time"},
        "lifecycle_transitions": _ACTION_FLAGS_SCHEMA,
        "actor_authorization": _ACTION_FLAGS_SCHEMA,
        "transport_blocker_codes": _STRING_ARRAY_SCHEMA,
        "event_payload_policy": {"type": "string", "enum": ["omitted_untyped"]},
        "risk_snapshot_policy": {"type": "string", "enum": ["content_hash_only"]},
        "risk_snapshot_content_hash": {
            "type": ["string", "null"],
            "pattern": "^[0-9a-f]{64}$",
        },
        "approval_evidence_status": {
            "type": "string",
            "enum": ["blocked", "display_only"],
        },
        "approval_evidence_blocker_codes": _STRING_ARRAY_SCHEMA,
        "approval_evidence": {"anyOf": [_EVIDENCE_SUMMARY_SCHEMA, {"type": "null"}]},
        "permission": {"type": "string", "enum": ["display_only"]},
        "must_not_use_for_decision": {"type": "boolean", "enum": [True]},
        "must_not_execute": {"type": "boolean", "enum": [True]},
    }
)


def _read(
    key: str,
    title: str,
    summary: str,
    executor_ref: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    enabled: bool = True,
    output_schema: dict[str, Any] | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        capability_key=key,
        title=title,
        summary=summary,
        description=(
            f"{summary} Reads persisted VPS projections only and never contacts QMT, leases "
            "orders, refreshes snapshots, or mutates state."
        ),
        owner_app="broker_execution",
        risk_level="low",
        executor_kind="internal_handler",
        executor_ref=executor_ref,
        tags=("broker_execution", "qmt", "实盘", "订单", "read"),
        input_schema={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        output_schema=output_schema or {"type": "object"},
        audit_tags=("broker_execution:read", "mcp:native"),
        legacy_tool_names=(),
        enabled=enabled,
    )


MANIFESTS = [
    _read(
        "broker_execution.read.overview",
        "Live Execution Readiness",
        "Read QMT live-execution readiness, stop state, pending approvals, and differences.",
        "get_broker_execution_overview",
        enabled=False,
    ),
    _read(
        "broker_execution.read.order_catalog",
        "Live Order Catalog",
        "List live orders visible to the authenticated account scope.",
        "list_broker_execution_orders",
        {
            "account_id": {"type": "integer", "minimum": 1},
            "status": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        enabled=False,
    ),
    _read(
        "broker_execution.read.order_detail",
        "Live Order Detail",
        "Read one order with approval evidence, broker events, and fills.",
        "get_broker_execution_order",
        {"client_order_id": {"type": "string", "format": "uuid"}},
        ["client_order_id"],
        enabled=True,
        output_schema=_ORDER_DETAIL_OUTPUT_SCHEMA,
    ),
    _read(
        "broker_execution.read.connection_status",
        "QMT Connection Status",
        "Read persisted Windows Agent, QMT, and account-binding health.",
        "get_broker_execution_connections",
        enabled=False,
    ),
    _read(
        "broker_execution.read.reconciliation_catalog",
        "Live Reconciliation Catalog",
        "List order, fill, cash, and position reconciliation evidence.",
        "list_broker_execution_reconciliations",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        enabled=False,
    ),
    _read(
        "broker_execution.read.audit_catalog",
        "Live Execution Audit",
        "List visible approval, cancel, stop, credential, and resolution audit events.",
        "list_broker_execution_audit",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        enabled=False,
    ),
]
