"""broker_execution strict-read MCP capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _read(
    key: str,
    title: str,
    summary: str,
    executor_ref: str,
    properties: dict | None = None,
    required: list[str] | None = None,
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
        output_schema={"type": "object"},
        audit_tags=("broker_execution:read", "mcp:native"),
        legacy_tool_names=(),
    )


MANIFESTS = [
    _read(
        "broker_execution.read.overview",
        "Live Execution Readiness",
        "Read QMT live-execution readiness, stop state, pending approvals, and differences.",
        "get_broker_execution_overview",
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
    ),
    _read(
        "broker_execution.read.order_detail",
        "Live Order Detail",
        "Read one order with approval evidence, broker events, and fills.",
        "get_broker_execution_order",
        {"client_order_id": {"type": "string", "format": "uuid"}},
        ["client_order_id"],
    ),
    _read(
        "broker_execution.read.connection_status",
        "QMT Connection Status",
        "Read persisted Windows Agent, QMT, and account-binding health.",
        "get_broker_execution_connections",
    ),
    _read(
        "broker_execution.read.reconciliation_catalog",
        "Live Reconciliation Catalog",
        "List order, fill, cash, and position reconciliation evidence.",
        "list_broker_execution_reconciliations",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
    ),
    _read(
        "broker_execution.read.audit_catalog",
        "Live Execution Audit",
        "List visible approval, cancel, stop, credential, and resolution audit events.",
        "list_broker_execution_audit",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
    ),
]
