"""Governed Fund capabilities backed by persisted research snapshots."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="fund.compute.screen",
        title="Screen Persisted Funds",
        summary="Screen persisted fund research snapshots with pure domain rules.",
        description=(
            "Apply fund type, style, scale, and performance scoring rules to persisted "
            "Fund records. The canonical endpoint does not seed the fund universe, "
            "synchronize providers, calculate missing performance snapshots, persist "
            "business records, or enqueue background work."
        ),
        owner_app="fund",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="fund_compute_screen",
        tags=("fund", "screen", "persisted", "research", "compute"),
        input_schema={
            "type": "object",
            "properties": {
                "regime": {
                    "type": ["string", "null"],
                    "enum": [
                        "Recovery",
                        "Overheat",
                        "Stagflation",
                        "Deflation",
                        None,
                    ],
                },
                "custom_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string", "maxLength": 50},
                    "maxItems": 20,
                },
                "custom_styles": {
                    "type": ["array", "null"],
                    "items": {"type": "string", "maxLength": 50},
                    "maxItems": 20,
                },
                "min_scale": {
                    "type": ["number", "null"],
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 30,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "regime": {"type": "string"},
                "fund_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "fund_names": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "screening_criteria": {"type": "object"},
                "error": {"type": ["string", "null"]},
            },
            "required": [
                "success",
                "regime",
                "fund_codes",
                "fund_names",
                "screening_criteria",
            ],
        },
        legacy_tool_names=("screen_funds",),
    ),
]
