"""Realtime alert and subscription management capability manifests."""

from __future__ import annotations

from typing import Any

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _write_manifest(
    *,
    capability_key: str,
    title: str,
    summary: str,
    description: str,
    executor_ref: str,
    tags: tuple[str, ...],
    properties: dict[str, Any],
    required: list[str],
    legacy_tool_names: tuple[str, ...],
) -> CapabilityManifest:
    """Build a consistently governed realtime write manifest."""

    return CapabilityManifest(
        capability_key=capability_key,
        title=title,
        summary=summary,
        description=description,
        owner_app="realtime",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref=executor_ref,
        tags=tags,
        input_schema={
            "type": "object",
            "properties": {
                **properties,
                "idempotency_key": {"type": "string"},
            },
            "required": required,
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=(f"realtime:{capability_key.split('.')[-1]}", "mcp:write"),
        legacy_tool_names=legacy_tool_names,
    )


MANIFESTS = [
    CapabilityManifest(
        capability_key="realtime.read.alerts",
        title="List Price Alerts",
        summary="List owner-scoped price alerts with optional status filtering.",
        description="Return only price alerts owned by the authenticated account.",
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_price_alerts",
        tags=("realtime", "alert", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        legacy_tool_names=("list_price_alerts",),
    ),
    CapabilityManifest(
        capability_key="realtime.read.alert",
        title="Get Price Alert",
        summary="Read one owner-scoped price alert.",
        description="Return one price alert only when it belongs to the authenticated account.",
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_price_alert",
        tags=("realtime", "alert", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {"alert_id": {"type": "integer", "minimum": 1}},
            "required": ["alert_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        legacy_tool_names=("get_price_alert",),
    ),
    CapabilityManifest(
        capability_key="realtime.read.price_subscriptions",
        title="List Price Subscriptions",
        summary="List durable price subscriptions for the authenticated owner.",
        description="Return active asset subscriptions owned by the authenticated account.",
        owner_app="realtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_price_subscriptions",
        tags=("realtime", "subscription", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        legacy_tool_names=("list_price_subscriptions",),
    ),
    _write_manifest(
        capability_key="realtime.create.price_alert",
        title="Create Price Alert",
        summary="Preview and confirm creation of a durable price alert.",
        description="Show the alert condition and threshold before creating it.",
        executor_ref="realtime_create_price_alert",
        tags=("realtime", "alert", "create", "write"),
        properties={
            "asset_code": {"type": "string"},
            "condition": {
                "type": "string",
                "enum": ["above", "below", "cross_up", "cross_down"],
            },
            "threshold": {"type": "number"},
            "message": {"type": "string"},
        },
        required=["asset_code", "condition", "threshold"],
        legacy_tool_names=("create_price_alert",),
    ),
    _write_manifest(
        capability_key="realtime.update.price_alert",
        title="Update Price Alert",
        summary="Preview and confirm changes to an owner-scoped price alert.",
        description="Show the current alert and requested fields before updating it.",
        executor_ref="realtime_update_price_alert",
        tags=("realtime", "alert", "update", "write"),
        properties={
            "alert_id": {"type": "integer", "minimum": 1},
            "condition": {
                "type": "string",
                "enum": ["above", "below", "cross_up", "cross_down"],
            },
            "threshold": {"type": "number"},
            "status": {"type": "string", "enum": ["active", "inactive"]},
            "message": {"type": "string"},
        },
        required=["alert_id"],
        legacy_tool_names=("update_price_alert",),
    ),
    _write_manifest(
        capability_key="realtime.delete.price_alert",
        title="Delete Price Alert",
        summary="Preview and confirm deletion of an owner-scoped price alert.",
        description="Show the selected alert before permanently deleting it.",
        executor_ref="realtime_delete_price_alert",
        tags=("realtime", "alert", "delete", "write"),
        properties={"alert_id": {"type": "integer", "minimum": 1}},
        required=["alert_id"],
        legacy_tool_names=("delete_price_alert",),
    ),
    _write_manifest(
        capability_key="realtime.create.price_subscription",
        title="Subscribe to Price Updates",
        summary="Preview and confirm a durable asset price subscription.",
        description="Show whether an asset is already subscribed before persisting it.",
        executor_ref="realtime_create_price_subscription",
        tags=("realtime", "subscription", "create", "write"),
        properties={"asset_code": {"type": "string"}},
        required=["asset_code"],
        legacy_tool_names=("subscribe_price",),
    ),
    _write_manifest(
        capability_key="realtime.delete.price_subscription",
        title="Unsubscribe from Price Updates",
        summary="Preview and confirm removal of a durable asset subscription.",
        description="Show whether the asset is currently subscribed before removing it.",
        executor_ref="realtime_delete_price_subscription",
        tags=("realtime", "subscription", "delete", "write"),
        properties={"asset_code": {"type": "string"}},
        required=["asset_code"],
        legacy_tool_names=("unsubscribe_price",),
    ),
]
