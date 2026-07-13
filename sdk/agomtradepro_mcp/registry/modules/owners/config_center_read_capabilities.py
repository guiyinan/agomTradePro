"""config_center read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="config_center.read.capability_catalog",
        title="Config Center Capability Catalog",
        summary="Read the configuration capabilities exposed by the canonical config center.",
        description=(
            "Return the staff-visible configuration capability catalog, including ownership, "
            "entry points, edit support, and operator documentation references."
        ),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_config_capabilities",
        tags=("config_center", "capability", "catalog", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "capabilities": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["capabilities", "total_count"],
        },
        required_roles=("staff",),
        legacy_tool_names=("list_config_capabilities",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.qlib_runtime",
        title="Config Center Qlib Runtime",
        summary="Read the canonical Qlib runtime configuration and health summary.",
        description=(
            "Return the configured Qlib paths, defaults, active model, training state, "
            "and validation errors without creating or updating system settings."
        ),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_qlib_runtime_config",
        tags=("config_center", "qlib", "runtime", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "configured": {"type": "boolean"},
                "enabled": {"type": "boolean"},
                "provider_uri": {"type": "string"},
                "region": {"type": "string"},
                "model_root": {"type": "string"},
                "active_model": {"type": ["object", "null"]},
                "training_task_running": {"type": "boolean"},
                "validation_errors": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "configured",
                "enabled",
                "provider_uri",
                "region",
                "model_root",
                "training_task_running",
                "validation_errors",
            ],
        },
        required_roles=("staff",),
        legacy_tool_names=("get_qlib_runtime_config",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.qlib_training_profiles",
        title="Config Center Qlib Training Profiles",
        summary="Read the canonical Qlib training-profile catalog.",
        description=("Return the reusable Qlib training profiles available to staff operators."),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_qlib_training_profiles",
        tags=("config_center", "qlib", "training", "profile", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "profiles": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["profiles", "total_count"],
        },
        required_roles=("staff",),
        legacy_tool_names=("list_qlib_training_profiles",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.alpha_universe_catalog",
        title="Config Center Alpha Universe Catalog",
        summary="Read the canonical Alpha and Qlib universe configuration catalog.",
        description=(
            "Return configured Alpha/Qlib universes, optionally including inactive entries."
        ),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_alpha_universes",
        tags=("config_center", "alpha", "qlib", "universe", "catalog", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "include_inactive": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "universes": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["universes", "total_count"],
        },
        required_roles=("staff",),
        legacy_tool_names=("list_alpha_universes",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.alpha_universe_members",
        title="Config Center Alpha Universe Members",
        summary="Read resolved members for one configured Alpha or Qlib universe.",
        description=(
            "Resolve one configured universe from persisted manual codes or the canonical "
            "data-center asset master without external refresh or persistence."
        ),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_alpha_universe_members",
        tags=("config_center", "alpha", "qlib", "universe", "members", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "universe_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["universe_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "universe_id": {"type": "string"},
                "member_count": {"type": "integer", "minimum": 0},
                "members": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["universe_id", "member_count", "members"],
        },
        required_roles=("staff",),
        legacy_tool_names=("get_alpha_universe_members",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.qlib_training_runs",
        title="Config Center Qlib Training Runs",
        summary="Read the recent canonical Qlib training-run list.",
        description=("Return recent persisted Qlib training runs and their execution status."),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_qlib_training_runs",
        tags=("config_center", "qlib", "training", "run", "list", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "runs": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["runs", "total_count"],
        },
        required_roles=("staff",),
        legacy_tool_names=("list_qlib_training_runs",),
    ),
    CapabilityManifest(
        capability_key="config_center.read.qlib_training_run_detail",
        title="Config Center Qlib Training Run Detail",
        summary="Read one canonical Qlib training-run record.",
        description=(
            "Return one persisted Qlib training run, including resolved configuration, "
            "result metadata, and error state."
        ),
        owner_app="config_center",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_qlib_training_run_detail",
        tags=("config_center", "qlib", "training", "run", "detail", "staff", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "minLength": 1},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "status": {"type": "string"},
                "model_name": {"type": "string"},
                "model_type": {"type": "string"},
                "resolved_train_config": {"type": "object"},
                "result_metrics": {"type": "object"},
                "error_message": {"type": "string"},
            },
            "required": ["run_id", "status", "model_name", "model_type"],
        },
        required_roles=("staff",),
        legacy_tool_names=("get_qlib_training_run_detail",),
    ),
]
