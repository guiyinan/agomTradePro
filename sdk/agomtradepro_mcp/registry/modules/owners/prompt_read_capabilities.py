"""prompt read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="prompt.read.template_catalog",
        title="Prompt Template Catalog",
        summary="Read the available prompt template catalog.",
        description=(
            "Return the active prompt template list exposed by the prompt service, "
            "including template identity, category, version, and execution defaults."
        ),
        owner_app="prompt",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_prompt_templates",
        tags=("prompt", "template", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "templates": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_prompt_templates",),
    ),
    CapabilityManifest(
        capability_key="prompt.read.chain_catalog",
        title="Prompt Chain Catalog",
        summary="Read the available prompt chain catalog.",
        description=(
            "Return the active prompt chain list exposed by the prompt service, "
            "including chain identity, category, execution mode, and step metadata."
        ),
        owner_app="prompt",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="list_prompt_chains",
        tags=("prompt", "chain", "catalog", "read"),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "chains": {"type": "array"},
                "total_count": {"type": "integer"},
            },
            "required": [],
        },
        legacy_tool_names=("list_prompt_chains",),
    ),
]
