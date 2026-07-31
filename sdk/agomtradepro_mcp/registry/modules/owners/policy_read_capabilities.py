"""policy read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="system.read.policy.status",
        title="Policy Status Snapshot",
        summary="Read the current policy gear and recent policy events.",
        description="Return the current policy status snapshot used by AgomTradePro.",
        owner_app="policy",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_policy_status",
        tags=("policy", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "current_gear": {"type": "string"},
                "observed_at": {"type": "string"},
                "recent_events_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_policy_status",),
    ),
    CapabilityManifest(
        capability_key="policy.read.events",
        title="Policy Events",
        summary="Read policy events for a time window.",
        description="Return policy events with event type, gear, and date for policy review workflows.",
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_policy_events",
        tags=("policy", "macro", "events", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["start_date", "end_date"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "events": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_policy_events",),
    ),
    CapabilityManifest(
        capability_key="policy.read.workbench.bootstrap",
        title="Policy Workbench Bootstrap",
        summary="Read the policy workbench bootstrap payload.",
        description=(
            "Return the policy workbench bootstrap data used to initialize the operator "
            "workbench, including summary, default list, filter options, trend, and fetch status."
        ),
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_workbench_bootstrap",
        tags=("policy", "workbench", "bootstrap", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "object"},
                "default_list": {"type": "array"},
                "filter_options": {"type": "object"},
                "trend": {"type": "object"},
                "fetch_status": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("get_workbench_bootstrap",),
    ),
    CapabilityManifest(
        capability_key="policy.read.workbench.summary",
        title="Policy Workbench Summary",
        summary="Read the policy workbench summary payload.",
        description=(
            "Return the policy workbench summary metrics used by operators, including "
            "policy level, gate level, and current review counters."
        ),
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_workbench_summary",
        tags=("policy", "workbench", "summary", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "policy_level": {"type": "string"},
                "policy_level_name": {"type": "string"},
                "gate_level": {"type": "string"},
                "gate_level_name": {"type": "string"},
                "global_heat": {},
                "global_sentiment": {},
                "pending_review_count": {"type": "integer"},
                "sla_exceeded_count": {"type": "integer"},
                "today_events_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_workbench_summary",),
    ),
    CapabilityManifest(
        capability_key="policy.read.workbench.event_detail",
        title="Policy Workbench Event Detail",
        summary="Read one policy workbench event detail payload.",
        description=(
            "Return one policy workbench event detail record, including source metadata, "
            "review state, and effective/reviewer names used by operator workflows."
        ),
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_workbench_event_detail",
        tags=("policy", "workbench", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
            },
            "required": ["event_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "audit_status": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_workbench_event_detail",),
    ),
    CapabilityManifest(
        capability_key="policy.read.workbench.items",
        title="Policy Workbench Items",
        summary="Read the policy workbench event list payload.",
        description=(
            "Return the operator-facing policy workbench event list, including filterable "
            "review items, pagination metadata, and gate status fields."
        ),
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_workbench_items",
        tags=("policy", "workbench", "items", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "tab": {"type": "string"},
                "event_type": {"type": "string"},
                "level": {"type": "string"},
                "gate_level": {"type": "string"},
                "search": {"type": "string"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "total_count": {"type": "integer"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("get_workbench_items",),
    ),
    CapabilityManifest(
        capability_key="policy.read.sentiment_gate.state",
        title="Policy Sentiment Gate State",
        summary="Read the current policy sentiment-gate state payload.",
        description=(
            "Return the policy sentiment-gate state used by operator workflows, including "
            "gate level, heat, sentiment, and position-cap guidance."
        ),
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_sentiment_gate_state",
        tags=("policy", "sentiment_gate", "state", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_class": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_class": {"type": "string"},
                "gate_level": {"type": "string"},
                "global_heat": {},
                "global_sentiment": {},
                "max_position_cap": {},
                "signal_paused": {"type": "boolean"},
                "data_sufficient": {"type": "boolean"},
                "must_not_use_for_decision": {"type": "boolean"},
                "blocked_reason": {"type": "string"},
            },
            "required": [],
        },
        legacy_tool_names=("get_sentiment_gate_state",),
    ),
]
