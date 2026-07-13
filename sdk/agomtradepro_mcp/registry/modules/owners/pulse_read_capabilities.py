"""pulse read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="pulse.read.current",
        title="Current Pulse Snapshot",
        summary="Read the current tactical pulse snapshot.",
        description=(
            "Return the current pulse dimensions, tactical composite score, and decision-safety contract."
        ),
        owner_app="pulse",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_pulse_current",
        tags=("pulse", "macro", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "composite_score": {"type": "number"},
            },
            "required": [],
        },
        legacy_tool_names=("get_pulse_current",),
    ),
    CapabilityManifest(
        capability_key="pulse.read.history",
        title="Pulse History",
        summary="Read recent pulse history snapshots.",
        description="Return recent pulse observations for tactical trend analysis.",
        owner_app="pulse",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_pulse_history",
        tags=("pulse", "macro", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "history": {"type": "array"},
            },
            "required": [],
        },
        legacy_tool_names=("get_pulse_history",),
    ),
]
