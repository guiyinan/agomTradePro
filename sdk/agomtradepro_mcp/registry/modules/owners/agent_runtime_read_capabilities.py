"""agent_runtime read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="agent_proposal.read.proposal_detail",
        title="Agent Proposal Detail",
        summary="Read one agent proposal and its lifecycle state.",
        description=(
            "Return one proposal with request identity, status, risk level, approval "
            "metadata, and proposal payload."
        ),
        owner_app="agent_runtime",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_agent_proposal",
        tags=("agent_runtime", "proposal", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "proposal_id": {"type": "integer"},
            },
            "required": ["proposal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "proposal": {"type": "object"},
            },
            "required": [],
        },
        legacy_tool_names=("get_agent_proposal",),
    ),
]
