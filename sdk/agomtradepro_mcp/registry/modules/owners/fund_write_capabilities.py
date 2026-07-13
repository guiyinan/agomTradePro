"""Fund workflow capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="fund.create.performance_snapshot",
        title="Create Fund Performance Snapshot",
        summary="Preview and confirm calculation of one persisted fund performance snapshot.",
        description=(
            "Resolve the requested period against local NAV dates, then calculate and "
            "persist canonical performance evidence only after confirmation."
        ),
        owner_app="fund",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="fund_create_performance_snapshot",
        tags=("fund", "performance", "snapshot", "create", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "fund_code": {"type": "string", "minLength": 1, "maxLength": 16},
                "period": {
                    "type": "string",
                    "enum": ["1m", "3m", "6m", "1y", "3y", "5y", "ytd", "inception"],
                },
                "idempotency_key": {"type": "string"},
            },
            "required": ["fund_code"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=("fund:create_performance_snapshot", "mcp:write"),
        legacy_tool_names=("get_fund_performance",),
    )
]
