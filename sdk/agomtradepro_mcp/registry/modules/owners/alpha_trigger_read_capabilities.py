"""alpha_trigger read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="alpha_trigger.read.trigger_list",
        title="Alpha Trigger List",
        summary="Read the canonical active Alpha trigger list.",
        description=(
            "Return the active Alpha triggers exposed by the canonical trigger list API. "
            "The governed contract is intentionally zero-parameter because the legacy raw "
            "tool and SDK do not publish the API's optional asset filter."
        ),
        owner_app="alpha_trigger",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_alpha_triggers",
        tags=("alpha_trigger", "trigger", "catalog", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "triggers": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["triggers", "total_count"],
        },
        legacy_tool_names=("list_alpha_triggers",),
    ),
    CapabilityManifest(
        capability_key="alpha_trigger.read.candidate_list",
        title="Alpha Candidate List",
        summary="Read the canonical actionable Alpha candidate list.",
        description=(
            "Return the actionable Alpha candidates exposed by the canonical unfiltered "
            "candidate list API. Filters are not published because the legacy raw tool and "
            "SDK currently expose only the zero-parameter contract."
        ),
        owner_app="alpha_trigger",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_alpha_candidates",
        tags=("alpha_trigger", "candidate", "actionable", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "candidates": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["candidates", "total_count"],
        },
        legacy_tool_names=("list_alpha_candidates",),
    ),
    CapabilityManifest(
        capability_key="alpha_trigger.read.candidate_detail",
        title="Alpha Candidate Detail",
        summary="Read one canonical Alpha candidate.",
        description=(
            "Return one Alpha candidate by candidate ID. The canonical API success envelope "
            "is normalized to the candidate object for governed callers."
        ),
        owner_app="alpha_trigger",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_alpha_candidate",
        tags=("alpha_trigger", "candidate", "detail", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "minLength": 1},
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "trigger_id": {"type": "string"},
                "asset_code": {"type": "string"},
                "status": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["candidate_id"],
        },
        legacy_tool_names=("get_alpha_candidate",),
    ),
    CapabilityManifest(
        capability_key="alpha_trigger.read.performance",
        title="Alpha Trigger Performance",
        summary="Read canonical Alpha trigger performance aggregates.",
        description=(
            "Return bounded performance aggregates for active Alpha triggers and their "
            "persisted candidates. This capability does not create triggers, update "
            "candidates, publish events, or start background tasks."
        ),
        owner_app="alpha_trigger",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="alpha_trigger_read_performance",
        tags=("alpha_trigger", "performance", "aggregate", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365},
                "trigger_id": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "maxLength": 64,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "array", "items": {"type": "object"}},
                "summary": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "minimum": 1, "maximum": 365},
                        "trigger_id": {"type": ["string", "null"]},
                        "total_triggers": {"type": "integer", "minimum": 0},
                    },
                    "required": ["days", "trigger_id", "total_triggers"],
                },
            },
            "required": ["success", "data", "summary"],
        },
        legacy_tool_names=("alpha_trigger_performance",),
    ),
]
