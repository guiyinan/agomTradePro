"""data_center write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="data_center.create.publisher",
        title="Create Data Center Publisher",
        summary="Preview the new publisher catalog entry, then confirm creating the publisher.",
        description=(
            "Normalize and summarize the requested publisher catalog definition first, "
            "then require explicit confirmation before creating the publisher entry "
            "through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_create_publisher",
        tags=("data_center", "publisher", "catalog", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "canonical_name": {"type": "string"},
                "publisher_class": {"type": "string"},
                "aliases": {"type": "array"},
                "canonical_name_en": {"type": "string"},
                "country_code": {"type": "string"},
                "website": {"type": "string"},
                "is_active": {"type": "boolean"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["code", "canonical_name", "publisher_class"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "canonical_name": {"type": "string"},
                "publisher_class": {"type": "string"},
                "aliases": {"type": "array"},
                "country_code": {"type": "string"},
                "website": {"type": "string"},
                "is_active": {"type": "boolean"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:create_publisher", "mcp:write"),
        legacy_tool_names=("data_center_create_publisher",),
    ),
    CapabilityManifest(
        capability_key="data_center.delete.publisher",
        title="Delete Data Center Publisher",
        summary="Preview the current publisher catalog entry, then confirm deleting the publisher.",
        description=(
            "Load the current publisher catalog definition first and summarize the "
            "publisher entry that will be removed, then require explicit confirmation "
            "before deleting it through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_delete_publisher",
        tags=("data_center", "publisher", "catalog", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "publisher_code": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["publisher_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "publisher_code": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:delete_publisher", "mcp:write"),
        legacy_tool_names=("data_center_delete_publisher",),
    ),
    CapabilityManifest(
        capability_key="data_center.update.publisher",
        title="Update Data Center Publisher",
        summary="Preview the current publisher catalog entry and requested changes, then confirm updating the publisher.",
        description=(
            "Load the current publisher catalog definition first and summarize the requested "
            "changes, then require explicit confirmation before updating the publisher entry "
            "through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_update_publisher",
        tags=("data_center", "publisher", "catalog", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "publisher_code": {"type": "string"},
                "canonical_name": {"type": "string"},
                "publisher_class": {"type": "string"},
                "aliases": {"type": "array"},
                "canonical_name_en": {"type": "string"},
                "country_code": {"type": "string"},
                "website": {"type": "string"},
                "is_active": {"type": "boolean"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["publisher_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "canonical_name": {"type": "string"},
                "publisher_class": {"type": "string"},
                "aliases": {"type": "array"},
                "country_code": {"type": "string"},
                "website": {"type": "string"},
                "is_active": {"type": "boolean"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:update_publisher", "mcp:write"),
        legacy_tool_names=("data_center_update_publisher",),
    ),
    CapabilityManifest(
        capability_key="data_center.create.indicator",
        title="Create Data Center Indicator",
        summary="Preview the new indicator catalog entry, then confirm creating the indicator.",
        description=(
            "Normalize and summarize the requested indicator catalog definition first, "
            "then require explicit confirmation before creating the indicator entry "
            "through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_create_indicator",
        tags=("data_center", "indicator", "catalog", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name_cn": {"type": "string"},
                "default_period_type": {"type": "string"},
                "name_en": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "is_active": {"type": "boolean"},
                "extra": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["code", "name_cn"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name_cn": {"type": "string"},
                "name_en": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "default_period_type": {"type": "string"},
                "is_active": {"type": "boolean"},
                "extra": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:create_indicator", "mcp:write"),
        legacy_tool_names=("data_center_create_indicator",),
    ),
    CapabilityManifest(
        capability_key="data_center.delete.indicator",
        title="Delete Data Center Indicator",
        summary="Preview the current indicator catalog entry, then confirm deleting the indicator.",
        description=(
            "Load the current indicator catalog definition first and summarize the "
            "indicator entry that will be removed, then require explicit confirmation "
            "before deleting it through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_delete_indicator",
        tags=("data_center", "indicator", "catalog", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "indicator_code": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:delete_indicator", "mcp:write"),
        legacy_tool_names=("data_center_delete_indicator",),
    ),
    CapabilityManifest(
        capability_key="data_center.create.indicator_unit_rule",
        title="Create Indicator Unit Rule",
        summary="Preview the new indicator unit rule, then confirm creating the rule.",
        description=(
            "Load the current indicator context first and summarize the requested "
            "unit-rule definition, then require explicit confirmation before creating "
            "the rule through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_create_indicator_unit_rule",
        tags=("data_center", "indicator", "unit_rule", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "source_type": {"type": "string"},
                "dimension_key": {"type": "string"},
                "original_unit": {"type": "string"},
                "storage_unit": {"type": "string"},
                "display_unit": {"type": "string"},
                "multiplier_to_storage": {"type": "number"},
                "is_active": {"type": "boolean"},
                "priority": {"type": "integer"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "indicator_code",
                "dimension_key",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
            ],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "indicator_code": {"type": "string"},
                "source_type": {"type": "string"},
                "dimension_key": {"type": "string"},
                "original_unit": {"type": "string"},
                "storage_unit": {"type": "string"},
                "display_unit": {"type": "string"},
                "multiplier_to_storage": {"type": "number"},
                "is_active": {"type": "boolean"},
                "priority": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:create_indicator_unit_rule", "mcp:write"),
        legacy_tool_names=("data_center_create_indicator_unit_rule",),
    ),
    CapabilityManifest(
        capability_key="data_center.delete.indicator_unit_rule",
        title="Delete Indicator Unit Rule",
        summary="Preview the current indicator unit rule, then confirm deleting the rule.",
        description=(
            "Load the current indicator unit-rule definition first and summarize the "
            "rule that will be removed, then require explicit confirmation before "
            "deleting it through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_delete_indicator_unit_rule",
        tags=("data_center", "indicator", "unit_rule", "delete", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code", "rule_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:delete_indicator_unit_rule", "mcp:write"),
        legacy_tool_names=("data_center_delete_indicator_unit_rule",),
    ),
    CapabilityManifest(
        capability_key="data_center.update.indicator_unit_rule",
        title="Update Indicator Unit Rule",
        summary="Preview the current indicator unit rule and requested changes, then confirm updating the rule.",
        description=(
            "Load the current indicator unit-rule definition first and summarize the "
            "requested changes, then require explicit confirmation before updating "
            "the rule through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_update_indicator_unit_rule",
        tags=("data_center", "indicator", "unit_rule", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "rule_id": {"type": "integer"},
                "source_type": {"type": "string"},
                "dimension_key": {"type": "string"},
                "original_unit": {"type": "string"},
                "storage_unit": {"type": "string"},
                "display_unit": {"type": "string"},
                "multiplier_to_storage": {"type": "number"},
                "is_active": {"type": "boolean"},
                "priority": {"type": "integer"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code", "rule_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "indicator_code": {"type": "string"},
                "source_type": {"type": "string"},
                "dimension_key": {"type": "string"},
                "original_unit": {"type": "string"},
                "storage_unit": {"type": "string"},
                "display_unit": {"type": "string"},
                "multiplier_to_storage": {"type": "number"},
                "is_active": {"type": "boolean"},
                "priority": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:update_indicator_unit_rule", "mcp:write"),
        legacy_tool_names=("data_center_update_indicator_unit_rule",),
    ),
    CapabilityManifest(
        capability_key="data_center.start.sync_job",
        title="Start Data Center Sync Job",
        summary="Preview the selected data-center sync job scope, then confirm starting the sync write.",
        description=(
            "Load the current provider and indicator context first, then require "
            "explicit confirmation before starting the selected data-center sync job. "
            "The initial governed subpaths are sync_macro, sync_capital_flows, and sync_news."
        ),
        owner_app="data_center",
        risk_level="medium",
        executor_kind="internal_handler",
        executor_ref="data_center_start_sync_job",
        tags=("data_center", "sync", "job", "macro", "start", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "job_kind": {
                    "type": "string",
                    "enum": ["sync_macro", "sync_capital_flows", "sync_news"],
                },
                "provider_id": {"type": "integer"},
                "indicator_code": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "asset_code": {"type": "string"},
                "period": {"type": "string"},
                "limit": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["job_kind", "provider_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "provider_name": {"type": "string"},
                "stored_count": {"type": "integer"},
                "status": {"type": "string"},
                "error_message": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:start_sync_job", "mcp:write"),
        legacy_tool_names=(
            "data_center_sync_macro",
            "data_center_sync_capital_flows",
            "data_center_sync_news",
        ),
    ),
    CapabilityManifest(
        capability_key="data_center.update.indicator",
        title="Update Data Center Indicator",
        summary="Preview the current indicator catalog entry and requested changes, then confirm updating the indicator.",
        description=(
            "Load the current indicator catalog definition first and summarize the requested "
            "changes, then require explicit confirmation before updating the indicator entry "
            "through the existing data-center write path."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_update_indicator",
        tags=("data_center", "indicator", "catalog", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "name_cn": {"type": "string"},
                "name_en": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "default_period_type": {"type": "string"},
                "is_active": {"type": "boolean"},
                "extra": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "name_cn": {"type": "string"},
                "name_en": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "default_period_type": {"type": "string"},
                "is_active": {"type": "boolean"},
                "extra": {"type": "object"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("data_center:update_indicator", "mcp:write"),
        legacy_tool_names=("data_center_update_indicator",),
    ),
    CapabilityManifest(
        capability_key="data_center.run.provider_connection_test",
        title="Run Data Center Provider Connection Test",
        summary="Preview provider probe side effects, then confirm the external connection test.",
        description=(
            "Load only safe provider metadata for preview, disclose the real external "
            "probe and provider health metadata write, then require explicit staff "
            "confirmation before invoking the canonical SDK connection-test endpoint."
        ),
        owner_app="data_center",
        risk_level="medium",
        executor_kind="internal_handler",
        executor_ref="data_center_run_provider_connection_test",
        tags=(
            "data_center",
            "provider",
            "connection_test",
            "external_io",
            "run",
            "write",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string"},
            },
            "required": ["provider_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "status": {"type": "string"},
                "summary": {"type": "string"},
                "logs": {"type": "array"},
                "tested_at": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("data_center:provider_connection_test", "mcp:write"),
        legacy_tool_names=("test_data_center_provider_connection",),
    ),
]

MANIFESTS.append(
    CapabilityManifest(
        capability_key="data_center.repair.decision_reliability",
        title="Repair Decision Data Reliability",
        summary="Preview and confirm a bounded multi-domain decision-data repair.",
        description=(
            "Show the target date, portfolio, asset, macro-indicator, freshness, and strictness "
            "scope before repairing macro, quote, Pulse, and Alpha reliability inputs."
        ),
        owner_app="data_center",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="data_center_repair_decision_reliability",
        tags=("data_center", "decision", "reliability", "repair", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "target_date": {"type": ["string", "null"], "format": "date"},
                "portfolio_id": {"type": ["integer", "null"], "minimum": 1},
                "asset_codes": {"type": ["array", "null"], "items": {"type": "string"}},
                "macro_indicator_codes": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "strict": {"type": "boolean"},
                "quote_max_age_hours": {"type": ["number", "null"], "minimum": 0},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("data_center:repair_decision_reliability", "mcp:write"),
        legacy_tool_names=("data_center_repair_decision_data_reliability",),
    )
)
