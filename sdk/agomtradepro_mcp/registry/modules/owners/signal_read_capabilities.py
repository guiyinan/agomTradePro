"""signal read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="signal.read.list",
        title="Investment Signal List",
        summary="Read investment signals with optional status and asset filters.",
        description=(
            "Return investment signals for review, optionally filtered by workflow status "
            "or asset code."
        ),
        owner_app="signal",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_signals",
        tags=("signal", "investment", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": ["string", "null"]},
                "asset_code": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "signals": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_signals",),
    ),
    CapabilityManifest(
        capability_key="signal.read.detail",
        title="Investment Signal Detail",
        summary="Read one investment signal and its invalidation contract.",
        description=(
            "Return one investment signal, including status, investment logic, invalidation "
            "logic, approval metadata, and creator information."
        ),
        owner_app="signal",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_signal",
        tags=("signal", "investment", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "signal_id": {"type": "integer"},
            },
            "required": ["signal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "asset_code": {"type": "string"},
                "logic_desc": {"type": "string"},
                "status": {"type": "string"},
                "created_at": {"type": ["string", "null"]},
                "invalidation_logic": {"type": ["string", "null"]},
                "invalidation_threshold": {"type": ["number", "null"]},
                "approved_at": {"type": ["string", "null"]},
                "invalidated_at": {"type": ["string", "null"]},
                "created_by": {},
            },
            "required": [],
        },
        legacy_tool_names=("get_signal",),
    ),
    CapabilityManifest(
        capability_key="signal.check.eligibility",
        title="Investment Signal Eligibility Check",
        summary="Check whether an investment signal is eligible in the current regime.",
        description=(
            "Evaluate an asset and investment thesis against the current regime and policy "
            "eligibility rules without creating or mutating a signal."
        ),
        owner_app="signal",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="check_signal_eligibility",
        tags=("signal", "investment", "eligibility", "check", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string"},
                "logic_desc": {"type": "string"},
            },
            "required": ["asset_code", "logic_desc"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "is_eligible": {"type": "boolean"},
                "regime_match": {"type": "boolean"},
                "policy_match": {"type": "boolean"},
                "current_regime": {"type": ["string", "null"]},
                "policy_status": {"type": ["string", "null"]},
                "rejection_reason": {"type": ["string", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("check_signal_eligibility",),
    ),
]
