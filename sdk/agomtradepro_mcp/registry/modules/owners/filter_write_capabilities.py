"""filter write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest
from agomtradepro_mcp.registry.modules.owners.filter_lifecycle import FILTER_LIFECYCLE

MANIFESTS = [
    CapabilityManifest(
        capability_key="filter.create.filter",
        title="Create Filter Run",
        summary="Preview a filter run without saving results, then confirm creating the persisted filter run.",
        description=(
            "Run the requested filter calculation first with save_results disabled and summarize "
            "the preview result, then require explicit confirmation before re-running the same "
            "filter request with save_results enabled."
        ),
        owner_app="filter",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="filter_create_filter",
        tags=("filter", "apply", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "filter_type": {"type": "string", "enum": ["HP", "KALMAN"]},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "limit": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "series": {"type": "object"},
                "warnings": {"type": "array"},
                "error": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("filter:create_filter", "mcp:write"),
        legacy_tool_names=("create_filter",),
        **FILTER_LIFECYCLE,
    ),
    CapabilityManifest(
        capability_key="filter.update.filter",
        title="Update Filter Config",
        summary="Preview the current filter config and requested changes, then confirm updating the filter config.",
        description=(
            "Load the current filter configuration by indicator code first and summarize the "
            "requested changes, then require explicit confirmation before updating the filter "
            "config through the canonical filter-config write path."
        ),
        owner_app="filter",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="filter_update_filter",
        tags=("filter", "config", "update", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "hp_enabled": {"type": "boolean"},
                "hp_lambda": {"type": "number"},
                "kalman_enabled": {"type": "boolean"},
                "kalman_level_variance": {"type": "number"},
                "kalman_slope_variance": {"type": "number"},
                "kalman_observation_variance": {"type": "number"},
                "description": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["indicator_code"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "indicator_code": {"type": "string"},
                "hp_enabled": {"type": "boolean"},
                "hp_lambda": {"type": "number"},
                "kalman_enabled": {"type": "boolean"},
                "kalman_level_variance": {"type": "number"},
                "kalman_slope_variance": {"type": "number"},
                "kalman_observation_variance": {"type": "number"},
                "description": {"type": "string"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("filter:update_filter", "mcp:write"),
        legacy_tool_names=("update_filter",),
        **FILTER_LIFECYCLE,
    ),
    CapabilityManifest(
        capability_key="filter.delete.filter",
        title="Delete Filter Config",
        summary="Preview the current filter config override, then confirm deleting the config override.",
        description=(
            "Load the current filter configuration by indicator code first and summarize the "
            "override that will be removed, then require explicit confirmation before deleting "
            "the persisted filter-config override."
        ),
        owner_app="filter",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="filter_delete_filter",
        tags=("filter", "config", "delete", "write"),
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
        audit_tags=("filter:delete_filter", "mcp:write"),
        legacy_tool_names=("delete_filter",),
        **FILTER_LIFECYCLE,
    ),
]
