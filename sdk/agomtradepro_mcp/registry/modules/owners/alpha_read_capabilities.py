"""alpha read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="alpha.read.provider_status",
        title="Alpha Provider Status",
        summary="Read the canonical Alpha provider health map.",
        description=(
            "Return the current status, priority, staleness allowance, and optional "
            "error for each registered Alpha provider."
        ),
        owner_app="alpha",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_alpha_provider_status",
        tags=("alpha", "provider", "health", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                    "status": {"type": "string"},
                    "max_staleness_days": {"type": "integer"},
                    "error": {"type": ["string", "null"]},
                },
            },
        },
        legacy_tool_names=("get_alpha_provider_status",),
    ),
    CapabilityManifest(
        capability_key="alpha.read.universe_catalog",
        title="Alpha Universe Catalog",
        summary="Read the canonical Alpha universe catalog.",
        description=(
            "Return the sorted union of Alpha service universes and any actor-visible "
            "Config Center universe definitions."
        ),
        owner_app="alpha",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_alpha_available_universes",
        tags=("alpha", "universe", "catalog", "research", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "universes": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
        legacy_tool_names=("get_alpha_available_universes",),
    ),
    CapabilityManifest(
        capability_key="alpha.read.health",
        title="Alpha Health",
        summary="Read the canonical Alpha service health summary.",
        description=(
            "Return the current Alpha health status, observation timestamp, and "
            "available-versus-total provider counts."
        ),
        owner_app="alpha",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="check_alpha_health",
        tags=("alpha", "provider", "health", "operations", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "timestamp": {"type": "string"},
                "providers": {
                    "type": "object",
                    "properties": {
                        "available": {"type": "integer"},
                        "total": {"type": "integer"},
                    },
                },
            },
            "required": [],
        },
        legacy_tool_names=("check_alpha_health",),
    ),
    CapabilityManifest(
        capability_key="alpha.read.inference_ops_overview",
        title="Alpha Inference Operations Overview",
        summary="Read the staff-only Alpha inference operations overview.",
        description=(
            "Return the active model, Qlib runtime state, Celery health, active refresh "
            "locks, recent inference tasks, score caches, and alerts without triggering "
            "inference, clearing locks, or initializing runtime settings."
        ),
        owner_app="alpha",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="alpha_read_inference_ops_overview",
        tags=("alpha", "inference", "operations", "staff", "read"),
        required_roles=("staff",),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "active_model": {"type": ["object", "null"]},
                "qlib_runtime": {"type": "object"},
                "celery_health": {"type": "object"},
                "dashboard_refresh_locks": {"type": "array"},
                "recent_tasks": {"type": "array"},
                "recent_caches": {"type": "array"},
                "recent_alerts": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("get_alpha_ops_inference_overview",),
    ),
    CapabilityManifest(
        capability_key="alpha.read.qlib_data_ops_overview",
        title="Qlib Data Operations Overview",
        summary="Read the staff-only Qlib runtime-data operations overview.",
        description=(
            "Return Qlib runtime configuration, local calendar freshness, recent refresh "
            "tasks, and the latest persisted build summary without refreshing files, "
            "queuing tasks, or initializing runtime settings."
        ),
        owner_app="alpha",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="alpha_read_qlib_data_ops_overview",
        tags=("alpha", "qlib", "data", "operations", "staff", "read"),
        required_roles=("staff",),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "qlib_runtime": {"type": "object"},
                "local_data_status": {"type": "object"},
                "recent_tasks": {"type": "array"},
                "latest_build_summary": {"type": ["object", "null"]},
            },
            "required": [],
        },
        legacy_tool_names=("get_alpha_ops_qlib_data_overview",),
    ),
]
