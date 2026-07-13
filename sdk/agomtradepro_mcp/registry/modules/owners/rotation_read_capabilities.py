"""rotation read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="rotation.read.regime_catalog",
        title="Rotation Regime Catalog",
        summary="Read the canonical macro-regime keys supported by rotation configuration.",
        description=("Return the regime keys used by account rotation allocation editors."),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_rotation_regimes",
        tags=("rotation", "regime", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "regimes": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["regimes", "total_count"],
        },
        legacy_tool_names=("list_rotation_regimes",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.template_catalog",
        title="Rotation Template Catalog",
        summary="Read the active canonical account-rotation templates.",
        description=("Return active database-backed rotation templates and regime allocations."),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_rotation_templates",
        tags=("rotation", "template", "allocation", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "templates": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["templates", "total_count"],
        },
        legacy_tool_names=("list_rotation_templates",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.config_detail",
        title="Rotation Strategy Config Detail",
        summary="Read one persisted rotation strategy configuration by name.",
        description=(
            "Read the authenticated canonical rotation config catalog and return one "
            "persisted strategy config by exact config_name. The result uses one stable "
            "success/config/available_configs/error envelope for found and not-found cases."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="rotation_read_config_detail",
        tags=("rotation", "strategy", "config", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "config_name": {"type": "string", "minLength": 1},
            },
            "required": ["config_name"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "config": {"type": ["object", "null"]},
                "available_configs": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "error": {"type": ["string", "null"]},
            },
            "required": ["success", "config", "available_configs", "error"],
        },
        legacy_tool_names=("get_rotation_config",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.account_config_list",
        title="Rotation Account Config List",
        summary="Read rotation configurations visible to the authenticated user's accounts.",
        description=(
            "Return account-level rotation configurations after canonical user-scope filtering."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_account_rotation_configs",
        tags=("rotation", "account", "config", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "configs": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["configs", "total_count"],
        },
        legacy_tool_names=("list_account_rotation_configs",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.account_config_detail",
        title="Rotation Account Config Detail",
        summary="Read one user-scoped account rotation configuration.",
        description=(
            "Return one account-level rotation configuration by config ID or account ID. "
            "Exactly one identifier must be supplied."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_account_rotation_config",
        tags=("rotation", "account", "config", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "config_id": {"type": ["integer", "null"], "minimum": 1},
                "account_id": {"type": ["integer", "null"], "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "account": {"type": "integer"},
                "risk_tolerance": {"type": "string"},
                "regime_allocations": {"type": "object"},
                "is_enabled": {"type": "boolean"},
            },
            "required": ["id", "account", "risk_tolerance", "regime_allocations", "is_enabled"],
        },
        legacy_tool_names=("get_account_rotation_config",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.asset_catalog",
        title="Rotation Asset Catalog",
        summary="Read the canonical rotation asset-master catalog.",
        description=("Return persisted rotation asset definitions without fetching live prices."),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_rotation_asset_master",
        tags=("rotation", "asset", "master", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "assets": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["assets", "total_count"],
        },
        legacy_tool_names=("list_rotation_asset_master",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.asset_detail",
        title="Rotation Asset Detail",
        summary="Read one canonical rotation asset-master record.",
        description=(
            "Return one persisted rotation asset definition by asset code without live-price access."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_rotation_asset",
        tags=("rotation", "asset", "master", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_code": {"type": "string", "minLength": 1},
            },
            "required": ["asset_code"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "code": {"type": "string"},
                "name": {"type": "string"},
                "category": {"type": "string"},
                "currency": {"type": "string"},
                "is_active": {"type": "boolean"},
            },
            "required": ["id", "code", "name", "category", "currency", "is_active"],
        },
        legacy_tool_names=("get_rotation_asset",),
    ),
    CapabilityManifest(
        capability_key="rotation.read.latest_signal_list",
        title="Rotation Latest Signal List",
        summary="Read the latest persisted signal for each active rotation configuration.",
        description=(
            "Return persisted latest rotation signals with freshness, quality, actionability, "
            "and execution-block metadata. This capability never generates a new signal."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_latest_rotation_signals",
        tags=("rotation", "signal", "latest", "quality", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "signals": {"type": "array", "items": {"type": "object"}},
                "total_count": {"type": "integer", "minimum": 0},
            },
            "required": ["signals", "total_count"],
        },
        legacy_tool_names=("get_latest_rotation_signals",),
    ),
    CapabilityManifest(
        capability_key="rotation.compute.asset_comparison",
        title="Rotation Asset Momentum Comparison",
        summary="Compare fixed-horizon momentum metrics for selected assets.",
        description=(
            "Compute fixed 1-month, 3-month, and 6-month momentum, moving-average, "
            "and trend metrics from persisted price facts. The calculation does not "
            "resolve Regime, persist Rotation records, or write successful price reads "
            "back to the process cache."
        ),
        owner_app="rotation",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="rotation_compute_asset_comparison",
        tags=("rotation", "asset", "momentum", "comparison", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_codes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 20,
                },
            },
            "required": ["asset_codes"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "calc_date": {"type": "string"},
                "assets": {"type": "object"},
            },
            "required": ["calc_date", "assets"],
        },
        legacy_tool_names=("compare_assets",),
    ),
]
