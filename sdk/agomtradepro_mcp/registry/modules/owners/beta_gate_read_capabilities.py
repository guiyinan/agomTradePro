"""beta_gate read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="beta_gate.read.config_catalog",
        title="Beta Gate Configuration Catalog",
        summary="Read active Beta Gate configurations.",
        description=(
            "Return active Beta Gate configuration definitions with regime, policy, "
            "portfolio, version, and validity metadata."
        ),
        owner_app="beta_gate",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_beta_gate_configs",
        tags=("beta_gate", "configuration", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "configs": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_beta_gate_configs",),
    ),
    CapabilityManifest(
        capability_key="beta_gate.compute.config_comparison",
        title="Compare Persisted Beta Gate Configs",
        summary="Compare two persisted Beta Gate configurations without mutation.",
        description=(
            "Read two exact persisted Beta Gate configs through the canonical authenticated "
            "GET contract and return their stable field-level differences. This capability "
            "does not activate, create, update, or delete any configuration."
        ),
        owner_app="beta_gate",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="compare_beta_gate_configs",
        tags=("beta_gate", "configuration", "version", "comparison", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "version1": {"type": "string", "minLength": 1, "maxLength": 64},
                "version2": {"type": "string", "minLength": 1, "maxLength": 64},
            },
            "required": ["version1", "version2"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "config1": {"type": "object"},
                "config2": {"type": "object"},
                "differences": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["config1", "config2", "differences"],
        },
        legacy_tool_names=("compare_beta_gate_version",),
    ),
    CapabilityManifest(
        capability_key="beta_gate.compute.batch_evaluation",
        title="Evaluate a Beta Gate Asset Batch",
        summary="Evaluate a bounded asset batch against one persisted or default Beta Gate config.",
        description=(
            "Run the canonical authenticated Beta Gate batch evaluation contract. The "
            "server selects the active config for the requested risk profile, or a stable "
            "same-profile default when no persisted config exists. The operation returns "
            "in-memory decisions only and does not save configs, decisions, events, tasks, "
            "or trades."
        ),
        owner_app="beta_gate",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="beta_gate_compute_batch_evaluation",
        tags=("beta_gate", "asset", "batch", "evaluation", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "asset_codes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 32,
                    },
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                },
                "asset_class": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
                "current_regime": {
                    "type": "string",
                    "enum": ["Recovery", "Overheat", "Deflation", "Stagflation"],
                },
                "regime_confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "policy_level": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3,
                },
                "risk_profile": {
                    "type": "string",
                    "enum": ["conservative", "balanced", "aggressive"],
                    "default": "balanced",
                },
            },
            "required": [
                "asset_codes",
                "asset_class",
                "current_regime",
                "regime_confidence",
                "policy_level",
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "config": {"type": "object"},
                "query": {"type": "object"},
                "results": {"type": "array", "items": {"type": "object"}},
                "summary": {"type": "object"},
            },
            "required": ["config", "query", "results", "summary"],
        },
        legacy_tool_names=("test_beta_gate",),
    ),
]
