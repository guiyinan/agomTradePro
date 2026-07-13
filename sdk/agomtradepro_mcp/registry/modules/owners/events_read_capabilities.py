"""events read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="events.read.query",
        title="Event Query",
        summary="Query canonical domain-event records.",
        description=(
            "Return stored domain events filtered by event type, correlation identity, "
            "time range, and bounded result limit."
        ),
        owner_app="events",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="query_events",
        tags=("events", "event_store", "query", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "event_type": {"type": ["string", "null"]},
                "event_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "correlation_id": {"type": ["string", "null"]},
                "since": {
                    "type": ["string", "null"],
                    "format": "date-time",
                },
                "until": {
                    "type": ["string", "null"],
                    "format": "date-time",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": ["string", "null"]},
                "error_code": {"type": ["string", "null"]},
                "timestamp": {"type": "string"},
                "events": {"type": "array"},
                "total_count": {"type": "integer"},
                "queried_at": {"type": "string"},
                "has_more": {"type": "boolean"},
            },
            "required": [],
        },
        legacy_tool_names=("query_events",),
    ),
    CapabilityManifest(
        capability_key="events.read.metrics",
        title="Event Bus Metrics",
        summary="Read canonical event-bus processing metrics.",
        description=(
            "Return event publication and processing metrics, event-type distribution, "
            "active subscriptions, and current queue size."
        ),
        owner_app="events",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_event_metrics",
        tags=("events", "event_bus", "metrics", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": ["string", "null"]},
                "error_code": {"type": ["string", "null"]},
                "timestamp": {"type": "string"},
                "metrics": {"type": "object"},
                "events_by_type": {"type": "object"},
                "active_subscriptions": {"type": "integer"},
                "queue_size": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_event_metrics",),
    ),
    CapabilityManifest(
        capability_key="events.read.status",
        title="Event Bus Status",
        summary="Read the canonical event-bus runtime status.",
        description=(
            "Return event-bus running state, subscriber count, queue size, latest event "
            "time, and uptime metadata."
        ),
        owner_app="events",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_event_bus_status",
        tags=("events", "event_bus", "health", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": ["string", "null"]},
                "error_code": {"type": ["string", "null"]},
                "timestamp": {"type": "string"},
                "is_running": {"type": "boolean"},
                "total_subscribers": {"type": "integer"},
                "queue_size": {"type": "integer"},
                "last_event_at": {"type": ["string", "null"]},
                "uptime_seconds": {"type": "number"},
            },
            "required": [],
        },
        legacy_tool_names=("get_event_bus_status",),
    ),
]
