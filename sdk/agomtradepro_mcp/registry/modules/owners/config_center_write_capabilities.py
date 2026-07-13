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
