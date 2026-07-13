"""rotation write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="rotation.create.asset",
        title="Create Rotation Asset",
        summary="Preview a globally unique rotation asset, then confirm staff-only creation.",
        description=(
            "Validate the canonical Rotation asset fields and inspect the existing global "
            "asset code without mutation, then require explicit confirmation before creating "
            "the asset through the canonical Rotation SDK."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_create_asset",
        tags=("rotation", "asset", "catalog", "configuration", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "minLength": 1, "maxLength": 20},
                "name": {"type": "string", "minLength": 1, "maxLength": 100},
                "category": {
                    "type": "string",
                    "enum": [
                        "equity",
                        "bond",
                        "commodity",
                        "currency",
                        "alternative",
                    ],
                },
                "description": {"type": "string", "maxLength": 2000},
                "underlying_index": {"type": "string", "maxLength": 50},
                "currency": {"type": "string", "minLength": 1, "maxLength": 10},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["code", "name", "category"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "code": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "underlying_index": {"type": "string"},
                "currency": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("rotation:create_asset", "mcp:write", "catalog:global"),
        legacy_tool_names=("create_rotation_asset",),
    ),
    CapabilityManifest(
        capability_key="rotation.update.asset",
        title="Update Rotation Asset",
        summary="Preview global Rotation asset field changes, then confirm staff-only update.",
        description=(
            "Read the current global Rotation asset without mutation, validate an explicit "
            "partial update and summarize changed fields, then require confirmation before "
            "applying the PATCH through the canonical Rotation SDK."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_update_asset",
        tags=("rotation", "asset", "catalog", "configuration", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string", "minLength": 1, "maxLength": 20},
                "name": {"type": "string", "minLength": 1, "maxLength": 100},
                "category": {
                    "type": "string",
                    "enum": [
                        "equity",
                        "bond",
                        "commodity",
                        "currency",
                        "alternative",
                    ],
                },
                "description": {"type": "string", "maxLength": 2000},
                "underlying_index": {"type": "string", "maxLength": 50},
                "currency": {"type": "string", "minLength": 1, "maxLength": 10},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "code": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "underlying_index": {"type": "string"},
                "currency": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("rotation:update_asset", "mcp:write", "catalog:global"),
        legacy_tool_names=("update_rotation_asset",),
    ),
    CapabilityManifest(
        capability_key="rotation.delete.asset",
        title="Soft Delete Rotation Asset",
        summary="Preview global Rotation asset deactivation, then confirm staff-only soft delete.",
        description=(
            "Read the current global Rotation asset without mutation and disclose the "
            "active-to-inactive transition, then require confirmation before invoking the "
            "canonical SDK delete method. Physical deletion is not exposed."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_delete_asset",
        tags=("rotation", "asset", "catalog", "configuration", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string", "minLength": 1, "maxLength": 20},
                "idempotency_key": {"type": "string"},
            },
            "required": ["asset_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "code": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("rotation:delete_asset", "mcp:write", "catalog:global"),
        legacy_tool_names=("delete_rotation_asset",),
    ),
    CapabilityManifest(
        capability_key="rotation.import.default_assets",
        title="Import Default Rotation Assets",
        summary="Preview default asset create/reactivate/update actions, then confirm import.",
        description=(
            "Ask the canonical Rotation API to derive a read-only plan from the server-owned "
            "default asset registry and current database state, then require confirmation "
            "before creating, reactivating or updating global asset catalog rows."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_import_default_assets",
        tags=("rotation", "asset", "catalog", "configuration", "import", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "created": {"type": "integer"},
                "reactivated": {"type": "integer"},
                "updated": {"type": "integer"},
                "unchanged": {"type": "integer"},
                "existing": {"type": "integer"},
                "total_defaults": {"type": "integer"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("rotation:import_default_assets", "mcp:write", "catalog:global"),
        legacy_tool_names=("import_default_rotation_assets",),
    ),
    CapabilityManifest(
        capability_key="rotation.create.account_config",
        title="Create Account Rotation Config",
        summary="Preview account rotation config inputs, then confirm creation of the account rotation config.",
        description=(
            "Load the target account context and rotation payload summary first, then require "
            "explicit confirmation before creating the account rotation config."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_create_account_config",
        tags=("rotation", "account_config", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "is_enabled": {"type": "boolean"},
                "regime_allocations": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "account": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "is_enabled": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("rotation:create_account_config", "mcp:write"),
        legacy_tool_names=("create_account_rotation_config",),
    ),
    CapabilityManifest(
        capability_key="rotation.delete.account_config",
        title="Delete Account Rotation Config",
        summary="Preview the target account rotation config, then confirm deletion of the account rotation config.",
        description=(
            "Load the target account rotation config context first, then require explicit "
            "confirmation before deleting the account rotation config."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_delete_account_config",
        tags=("rotation", "account_config", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "config_id": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("rotation:delete_account_config", "mcp:write"),
        legacy_tool_names=("delete_account_rotation_config",),
    ),
    CapabilityManifest(
        capability_key="rotation.update.account_config",
        title="Update Account Rotation Config",
        summary="Preview the target account rotation config and requested changes, then confirm updating the account rotation config.",
        description=(
            "Load the current account rotation config context and summarize the requested "
            "changes first, then require explicit confirmation before updating the account "
            "rotation config."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_update_account_config",
        tags=("rotation", "account_config", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "payload": {"type": "object"},
                "partial": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id", "payload"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "id": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "is_enabled": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("rotation:update_account_config", "mcp:write"),
        legacy_tool_names=("update_account_rotation_config",),
    ),
    CapabilityManifest(
        capability_key="rotation.apply_template.account_config",
        title="Apply Rotation Template To Account Config",
        summary="Preview the target account rotation config and template selection, then confirm applying the template.",
        description=(
            "Load the current account rotation config and requested template context first, "
            "then require explicit confirmation before applying the template to the account "
            "rotation config."
        ),
        owner_app="rotation",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="rotation_apply_template_account_config",
        tags=("rotation", "account_config", "template", "apply", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": "integer"},
                "template_key": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_id", "template_key"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "id": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "is_enabled": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("rotation:apply_template_account_config", "mcp:write"),
        legacy_tool_names=("apply_rotation_template_to_account_config",),
    ),
]
