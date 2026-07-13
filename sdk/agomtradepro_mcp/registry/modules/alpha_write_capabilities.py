"""Governed Alpha write capability manifests."""

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="alpha.import.score_cache",
        title="Import Alpha Score Cache",
        summary="Preview one exact score-cache target, then confirm its batch upsert.",
        description=(
            "Validate and normalize a bounded Alpha score batch, preview the exact user or "
            "system Qlib cache target without writes, then require explicit confirmation "
            "before the canonical Alpha API performs the upsert."
        ),
        owner_app="alpha",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="alpha_import_score_cache",
        tags=("alpha", "score", "cache", "import", "batch", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "universe_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "asof_date": {"type": "string", "format": "date"},
                "intended_trade_date": {"type": "string", "format": "date"},
                "model_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "model_artifact_hash": {"type": "string", "maxLength": 64},
                "scope": {"type": "string", "enum": ["user", "system"]},
                "scores": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1000,
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "minLength": 1, "maxLength": 32},
                            "score": {"type": "number"},
                            "rank": {"type": "integer", "minimum": 1},
                            "factors": {"type": "object"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "source": {"type": "string", "minLength": 1, "maxLength": 64},
                        },
                        "required": ["code", "score", "rank"],
                        "additionalProperties": False,
                    },
                },
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "universe_id",
                "asof_date",
                "intended_trade_date",
                "scores",
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "count": {"type": "integer"},
                "scope": {"type": "string"},
                "id": {"type": "integer"},
                "created": {"type": "boolean"},
            },
            "required": [],
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        required_roles=("staff",),
        audit_tags=("alpha:score_cache_import", "mcp:write"),
        legacy_tool_names=("upload_alpha_scores",),
    )
]

MANIFESTS.extend(
    [
        CapabilityManifest(
            capability_key="alpha.start.inference",
            title="Start Alpha Inference",
            summary="Preview and confirm one staff-scoped Alpha inference task.",
            description=(
                "Inspect current inference operations state, then enqueue one bounded "
                "general, portfolio-scoped, or daily-scoped inference task."
            ),
            owner_app="alpha",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_start_inference",
            tags=("alpha", "inference", "task", "start", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["general", "portfolio_scoped", "daily_scoped_batch"],
                    },
                    "trade_date": {"type": ["string", "null"], "format": "date"},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 500},
                    "universe_id": {"type": ["string", "null"], "maxLength": 100},
                    "portfolio_id": {"type": ["integer", "null"], "minimum": 1},
                    "pool_mode": {"type": ["string", "null"], "maxLength": 64},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["mode"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("alpha:start_inference", "mcp:write"),
            legacy_tool_names=("trigger_alpha_ops_inference",),
        ),
        CapabilityManifest(
            capability_key="alpha.refresh.qlib_data",
            title="Refresh Alpha Qlib Data",
            summary="Preview and confirm one bounded Qlib data refresh task.",
            description=(
                "Inspect current Qlib data operations state, then enqueue one explicitly "
                "scoped universe or portfolio-code refresh task."
            ),
            owner_app="alpha",
            risk_level="high",
            executor_kind="internal_handler",
            executor_ref="alpha_refresh_qlib_data",
            tags=("alpha", "qlib", "data", "refresh", "write"),
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["universes", "scoped_codes"]},
                    "target_date": {"type": "string", "format": "date"},
                    "lookback_days": {"type": "integer", "minimum": 1, "maximum": 5000},
                    "universes": {"type": ["array", "null"], "items": {"type": "string"}},
                    "portfolio_ids": {
                        "type": ["array", "null"],
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "all_active_portfolios": {"type": "boolean"},
                    "pool_mode": {"type": ["string", "null"], "maxLength": 64},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["mode", "target_date"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {}, "required": []},
            requires_confirmation=True,
            confirmation_preview_arguments={"preview_only": True},
            confirmation_commit_arguments={"preview_only": False},
            idempotency="required",
            required_roles=("staff",),
            audit_tags=("alpha:refresh_qlib_data", "mcp:write"),
            legacy_tool_names=("refresh_alpha_qlib_data",),
        ),
    ]
)
