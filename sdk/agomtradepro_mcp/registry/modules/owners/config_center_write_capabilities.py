"""config_center write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="config_center.update.runtime_setting",
        title="Update Qlib Runtime Setting",
        summary="Preview the current Qlib runtime config and requested changes, then confirm updating the runtime setting.",
        description=(
            "Load the current Qlib runtime configuration and summarize the requested "
            "changes first, then require explicit confirmation before updating the "
            "runtime setting through the existing config-center write path."
        ),
        owner_app="config_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="config_center_update_runtime_setting",
        tags=("config_center", "qlib", "runtime", "settings", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "provider_uri": {"type": "string"},
                "region": {"type": "string"},
                "model_root": {"type": "string"},
                "default_universe": {"type": "string"},
                "default_feature_set_id": {"type": "string"},
                "default_label_id": {"type": "string"},
                "train_queue_name": {"type": "string"},
                "infer_queue_name": {"type": "string"},
                "allow_auto_activate": {"type": "boolean"},
                "alpha_fixed_provider": {"type": "string"},
                "alpha_pool_mode": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "configured": {"type": "boolean"},
                "enabled": {"type": "boolean"},
                "provider_uri": {"type": "string"},
                "region": {"type": "string"},
                "model_root": {"type": "string"},
                "default_universe": {"type": "string"},
                "default_feature_set_id": {"type": "string"},
                "default_label_id": {"type": "string"},
                "train_queue_name": {"type": "string"},
                "infer_queue_name": {"type": "string"},
                "allow_auto_activate": {"type": "boolean"},
                "alpha_fixed_provider": {"type": "string"},
                "alpha_pool_mode": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("config_center:update_runtime_setting", "mcp:write"),
        legacy_tool_names=("update_qlib_runtime_config",),
    ),
    CapabilityManifest(
        capability_key="config_center.create.data_center_provider",
        title="Create Data Center Provider",
        summary="Preview the new data-center provider config, then confirm creating the provider.",
        description=(
            "Normalize and summarize the requested data-center provider configuration "
            "first, then require explicit confirmation before creating the provider "
            "through the existing config-center write path."
        ),
        owner_app="config_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="config_center_create_data_center_provider",
        tags=("config_center", "data_center", "provider", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source_type": {"type": "string"},
                "priority": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "api_key": {"type": "string"},
                "http_url": {"type": "string"},
                "api_endpoint": {"type": "string"},
                "api_secret": {"type": "string"},
                "extra_config": {"type": "object"},
                "tushare_request_mode": {
                    "type": "string",
                    "enum": ["sdk_path", "unified_relay"],
                },
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["name", "source_type"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "source_type": {"type": "string"},
                "priority": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "http_url": {"type": "string"},
                "api_endpoint": {"type": "string"},
                "description": {"type": "string"},
                "tushare_request_mode": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("config_center:create_data_center_provider", "mcp:write"),
        legacy_tool_names=("create_data_center_provider",),
    ),
    CapabilityManifest(
        capability_key="config_center.update.data_center_provider",
        title="Update Data Center Provider",
        summary="Preview the current data-center provider config and requested changes, then confirm updating the provider.",
        description=(
            "Load the current provider configuration first and summarize the requested "
            "changes, then require explicit confirmation before updating the data-center "
            "provider through the existing config-center write path."
        ),
        owner_app="config_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="config_center_update_data_center_provider",
        tags=("config_center", "data_center", "provider", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
                "name": {"type": "string"},
                "source_type": {"type": "string"},
                "priority": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "api_key": {"type": "string"},
                "http_url": {"type": "string"},
                "api_endpoint": {"type": "string"},
                "api_secret": {"type": "string"},
                "extra_config": {"type": "object"},
                "tushare_request_mode": {
                    "type": "string",
                    "enum": ["sdk_path", "unified_relay"],
                },
                "clear_service_address": {"type": "boolean"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["provider_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "source_type": {"type": "string"},
                "priority": {"type": "integer"},
                "is_active": {"type": "boolean"},
                "http_url": {"type": "string"},
                "api_endpoint": {"type": "string"},
                "description": {"type": "string"},
                "tushare_request_mode": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("config_center:update_data_center_provider", "mcp:write"),
        legacy_tool_names=("update_data_center_provider",),
    ),
]

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="config_center.update.qlib_training_profile",
            title="Save Qlib Training Profile",
            summary="Preview and confirm a Qlib training-profile upsert.",
            description=(
                "Summarize the exact profile identity and changed fields before the "
                "superuser-scoped canonical API creates or updates the profile."
            ),
            owner_app="config_center",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="config_center_update_qlib_training_profile",
            tags=("config_center", "qlib", "training", "profile", "update", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("config_center:save_training_profile", "mcp:write"),
            legacy_tool_names=("save_qlib_training_profile",),
        ),
        CapabilityManifest(
            capability_key="config_center.update.alpha_universe",
            title="Save Alpha Universe",
            summary="Preview and confirm an Alpha universe upsert.",
            description=(
                "Summarize the universe identity, member count, and filters before the "
                "superuser-scoped canonical API creates or updates it."
            ),
            owner_app="config_center",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="config_center_update_alpha_universe",
            tags=("config_center", "alpha", "universe", "update", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("config_center:save_alpha_universe", "mcp:write"),
            legacy_tool_names=("save_alpha_universe",),
        ),
        CapabilityManifest(
            capability_key="config_center.start.qlib_training",
            title="Start Qlib Training",
            summary="Preview and confirm one asynchronous Qlib training run.",
            description=(
                "Summarize the model, profile, universe, date window, and activation flag "
                "before the superuser-scoped canonical API enqueues training."
            ),
            owner_app="config_center",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="config_center_start_qlib_training",
            tags=("config_center", "qlib", "training", "task", "start", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {"type": "object"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["payload"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("config_center:start_qlib_training", "mcp:write"),
            legacy_tool_names=("trigger_qlib_training",),
        ),
    ]
)
