"""broker_execution governed-write MCP capability manifests."""

from __future__ import annotations

from typing import Any

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _write(
    *,
    key: str,
    title: str,
    summary: str,
    executor_ref: str,
    properties: dict[str, Any],
    required: list[str],
    required_roles: tuple[str, ...] = (),
    enabled: bool = True,
) -> CapabilityManifest:
    return CapabilityManifest(
        capability_key=key,
        title=title,
        summary=summary,
        description=(
            f"{summary} The first call is preview-only; commit requires explicit confirmation, "
            "a unique idempotency key, server-side authorization, state validation, and audit."
        ),
        owner_app="broker_execution",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref=executor_ref,
        tags=("broker_execution", "qmt", "实盘", "订单", "write"),
        input_schema={
            "type": "object",
            "properties": {**properties, "idempotency_key": {"type": "string"}},
            "required": required,
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=required_roles,
        audit_tags=(
            f"broker_execution:{key.split('.')[-1]}",
            "mcp:write",
            "mcp:native",
        ),
        legacy_tool_names=(),
        enabled=enabled,
    )


_ORDER_FIELDS = {
    "client_order_id": {"type": "string", "format": "uuid"},
    "reason": {"type": "string", "minLength": 1},
    "expected_version": {"type": "integer", "minimum": 0},
}

MANIFESTS = [
    _write(
        key="broker_execution.approve.order",
        title="Approve Live Order",
        summary="Preview and approve an existing risk-checked live order.",
        executor_ref="broker_execution_approve_order",
        properties=_ORDER_FIELDS,
        required=["client_order_id", "reason", "expected_version"],
        required_roles=("admin", "owner", "investment_manager", "trader"),
        enabled=False,
    ),
    _write(
        key="broker_execution.reject.order",
        title="Reject Live Order",
        summary="Preview and reject an existing unsubmitted live order.",
        executor_ref="broker_execution_reject_order",
        properties=_ORDER_FIELDS,
        required=["client_order_id", "reason", "expected_version"],
        required_roles=("admin", "owner", "investment_manager", "trader", "risk"),
    ),
    _write(
        key="broker_execution.request.cancel",
        title="Request Broker Cancel",
        summary="Preview current order state and request cancellation without direct QMT access.",
        executor_ref="broker_execution_request_cancel",
        properties=_ORDER_FIELDS,
        required=["client_order_id", "reason", "expected_version"],
        required_roles=("admin", "owner", "investment_manager", "trader", "risk"),
    ),
    _write(
        key="broker_execution.trigger.kill_switch",
        title="Trigger Live Trading Stop",
        summary="Preview impact and stop new order leasing/submission for an account scope.",
        executor_ref="broker_execution_trigger_kill_switch",
        properties={
            "account_id": {"type": "integer", "minimum": 0},
            "reason": {"type": "string", "minLength": 1},
        },
        required=["account_id", "reason"],
        required_roles=("admin", "owner", "investment_manager", "trader", "risk"),
    ),
    _write(
        key="broker_execution.resume.trading",
        title="Resume Live Trading",
        summary="Preview readiness and restore live trading after an administrator check.",
        executor_ref="broker_execution_resume_trading",
        properties={
            "account_id": {"type": "integer", "minimum": 0},
            "reason": {"type": "string", "minLength": 1},
            "reauth_password": {
                "type": "string",
                "minLength": 1,
                "format": "password",
                "writeOnly": True,
            },
        },
        required=["account_id", "reason", "reauth_password"],
        required_roles=("admin",),
    ),
    _write(
        key="broker_execution.resolve.reconciliation",
        title="Resolve Live Reconciliation",
        summary="Preview a persisted difference resolution and mark it resolved after confirmation.",
        executor_ref="broker_execution_resolve_reconciliation",
        properties={
            "run_id": {"type": "integer", "minimum": 1},
            "resolution": {
                "type": "string",
                "enum": [
                    "accept_broker_fact",
                    "manual_adjustment",
                    "verified_no_change",
                    "escalate",
                ],
            },
            "reason": {"type": "string", "minLength": 1},
        },
        required=["run_id", "resolution", "reason"],
        required_roles=("admin", "risk"),
    ),
]
