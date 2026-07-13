"""Factor workflow capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="factor.create.portfolio",
        title="Create Factor Portfolio",
        summary="Preview and confirm creation of one persisted factor portfolio.",
        description=(
            "Show the factor config and trade date before calculating holdings and "
            "persisting the canonical portfolio result."
        ),
        owner_app="factor",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="factor_create_portfolio",
        tags=("factor", "portfolio", "holdings", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "config_name": {"type": "string", "minLength": 1, "maxLength": 128},
                "trade_date": {"type": ["string", "null"], "format": "date"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["config_name"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("factor:create_portfolio", "mcp:write"),
        legacy_tool_names=("create_factor_portfolio",),
    )
]
