"""decision_rhythm read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="decision_rhythm.read.quota_list",
        title="Decision Quota List",
        summary="Read the canonical decision quota list.",
        description=(
            "Return the default decision quota list. The governed contract remains "
            "zero-parameter because the legacy raw tool and SDK do not publish the "
            "canonical API's optional period and account filters."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_decision_quotas",
        tags=("decision_rhythm", "quota", "catalog", "governance", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "quotas": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["quotas", "total_count"],
        },
        legacy_tool_names=("list_decision_quotas",),
    ),
    CapabilityManifest(
        capability_key="decision_rhythm.read.request_list",
        title="Decision Request List",
        summary="Read the canonical recent decision request list.",
        description=(
            "Return the canonical default recent-request window. The governed contract "
            "does not publish days or asset filters because the legacy raw tool and SDK "
            "currently expose only the zero-parameter list."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_decision_requests",
        tags=("decision_rhythm", "request", "catalog", "decision", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "requests": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["requests", "total_count"],
        },
        legacy_tool_names=("list_decision_requests",),
    ),
    CapabilityManifest(
        capability_key="decision_rhythm.read.request_detail",
        title="Decision Request Detail",
        summary="Read one canonical decision request.",
        description=(
            "Return one decision request by request ID. The canonical success envelope "
            "is normalized to the request object for governed callers."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_decision_request",
        tags=("decision_rhythm", "request", "detail", "decision", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "minLength": 1},
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "asset_code": {"type": "string"},
                "priority": {"type": "string"},
                "execution_status": {"type": "string"},
            },
            "required": ["request_id"],
        },
        legacy_tool_names=("get_decision_request",),
    ),
    CapabilityManifest(
        capability_key="decision_rhythm.read.summary",
        title="Decision Rhythm Summary",
        summary="Read the canonical decision rhythm summary.",
        description=(
            "Return the current decision rhythm summary. The governed contract is "
            "zero-parameter because the canonical API ignores the legacy SDK payload."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_decision_rhythm_summary",
        tags=("decision_rhythm", "summary", "quota", "decision", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "additionalProperties": True,
        },
        legacy_tool_names=("get_decision_rhythm_summary",),
    ),
    CapabilityManifest(
        capability_key="decision.read.recommendation_list",
        title="Decision Recommendation List",
        summary="Read the canonical decision-workspace recommendation list.",
        description=(
            "Return one account's paginated unified recommendations. The canonical API "
            "success envelope is normalized to the recommendation-list data object."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="decision_workflow_list_recommendations",
        tags=("decision", "workspace", "recommendation", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "minLength": 1},
                "status": {"type": ["string", "null"]},
                "user_action": {"type": ["string", "null"]},
                "security_code": {"type": ["string", "null"]},
                "recommendation_id": {"type": ["string", "null"]},
                "include_ignored": {"type": "boolean"},
                "page": {"type": "integer", "minimum": 1},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "recommendations": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
                "page": {"type": "integer", "minimum": 1},
                "page_size": {"type": "integer", "minimum": 1},
            },
            "required": ["recommendations", "total_count", "page", "page_size"],
        },
        legacy_tool_names=("decision_workflow_list_recommendations",),
    ),
    CapabilityManifest(
        capability_key="decision.read.transition_plan_detail",
        title="Decision Transition Plan Detail",
        summary="Read one saved decision transition plan.",
        description=(
            "Return one persisted transition plan by plan ID. The canonical API success "
            "envelope is normalized to the transition-plan data object."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="decision_workflow_get_transition_plan",
        tags=("decision", "workspace", "transition_plan", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "minLength": 1},
            },
            "required": ["plan_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "account_id": {"type": "string"},
                "status": {"type": "string"},
                "current_positions": {"type": "array"},
                "target_positions": {"type": "array"},
                "orders": {"type": "array"},
                "risk_contract": {"type": "object"},
                "summary": {"type": "object"},
            },
            "required": ["plan_id", "account_id", "status", "orders"],
        },
        legacy_tool_names=("decision_workflow_get_transition_plan",),
    ),
    CapabilityManifest(
        capability_key="decision.read.advisor_sheet",
        title="Auto Advisor Decision Sheet",
        summary="Read the current account-level auto-advisor decision sheet.",
        description=(
            "Return the authenticated user's current account snapshot, holdings, allocation, "
            "risk context, order intents, blockers, and confirmation-only execution plan. "
            "The capability does not execute trades or persist advisor outputs."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="decision_read_advisor_sheet",
        tags=("decision", "auto_advisor", "account", "sheet", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "string"]},
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "account": {"type": "object"},
                "baseline": {"type": "string"},
                "generated_at": {"type": "string"},
                "today_conclusion": {"type": "string"},
                "risk_policy": {"type": "object"},
                "data_health": {"type": "object"},
                "holdings": {"type": "array"},
                "allocation": {"type": "array"},
                "order_summary": {"type": "object"},
                "order_intents": {"type": "array"},
                "execution_plan": {"type": "object"},
                "blockers": {"type": "array"},
                "warnings": {"type": "array"},
                "next_actions": {"type": "array"},
            },
            "required": [
                "account",
                "baseline",
                "generated_at",
                "today_conclusion",
                "data_health",
                "holdings",
                "allocation",
                "order_summary",
                "order_intents",
                "execution_plan",
                "blockers",
                "next_actions",
            ],
        },
        legacy_tool_names=("get_auto_advisor_decision_sheet",),
    ),
    CapabilityManifest(
        capability_key="decision.compute.workflow_precheck",
        title="Decision Workflow Precheck",
        summary="Evaluate whether one Alpha candidate can enter the decision workflow.",
        description=(
            "Read candidate, Beta Gate, quota, and cooldown state and return a bounded "
            "precheck result without submitting or mutating a decision request."
        ),
        owner_app="decision_rhythm",
        risk_level="medium",
        executor_kind="legacy_tool",
        executor_ref="decision_compute_workflow_precheck",
        tags=("decision", "workflow", "precheck", "guardrail", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "minLength": 1, "maxLength": 128}
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "result": {"type": "object"},
                "error": {"type": ["string", "null"]},
            },
            "required": ["success"],
        },
        audit_tags=("decision:workflow_precheck", "mcp:research_read"),
        legacy_tool_names=("decision_workflow_precheck",),
    ),
    CapabilityManifest(
        capability_key="decision.read.funnel_context",
        title="Decision Funnel Context",
        summary="Read the canonical decision funnel and attribution context.",
        description=(
            "Return environment, direction, sector, and optional attribution context "
            "without refreshing recommendations or changing workflow state."
        ),
        owner_app="decision_rhythm",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="decision_read_funnel_context",
        tags=("decision", "funnel", "context", "attribution", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "trade_id": {"type": "string", "maxLength": 128},
                "backtest_id": {"type": ["integer", "null"], "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("decision_workflow_get_funnel_context",),
    ),
]
