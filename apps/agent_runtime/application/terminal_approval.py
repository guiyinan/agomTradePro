"""Durable approval facade for Terminal-originated MCP capability calls."""

from __future__ import annotations

from typing import Any

from apps.agent_runtime.application.proposal_use_cases import (
    CreateProposalInput,
    CreateProposalUseCase,
    SubmitProposalForApprovalUseCase,
)

TERMINAL_MCP_PROPOSAL_TYPE = "terminal_mcp_capability"


class TerminalMcpApprovalFacade:
    """Create and submit persistent proposals for gated MCP capabilities."""

    def __init__(
        self,
        *,
        create_use_case: CreateProposalUseCase | None = None,
        submit_use_case: SubmitProposalForApprovalUseCase | None = None,
    ) -> None:
        self._create_use_case = create_use_case or CreateProposalUseCase()
        self._submit_use_case = submit_use_case or SubmitProposalForApprovalUseCase()

    def stage_terminal_mcp_capability(
        self,
        *,
        capability_key: str,
        arguments: dict[str, Any],
        risk_level: str,
        summary: str,
        session_id: str,
        user_id: int | None,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an immutable execution payload and submit it for approval."""

        created = self._create_use_case.execute(
            CreateProposalInput(
                proposal_type=TERMINAL_MCP_PROPOSAL_TYPE,
                risk_level=risk_level,
                approval_required=True,
                proposal_payload={
                    "source": "terminal_mcp",
                    "capability_key": capability_key,
                    "arguments": dict(arguments),
                    "session_id": session_id,
                    "summary": summary,
                },
                approval_reason=(
                    f"Terminal MCP capability '{capability_key}' requires explicit approval"
                ),
                created_by=user_id,
            )
        )
        proposal_id = created.proposal.id
        if proposal_id is None:
            raise RuntimeError("agent_proposal_persistence_missing_id")
        submitted = self._submit_use_case.execute(
            proposal_id=proposal_id,
            actor=actor,
            context={},
        )
        return {
            "proposal_id": submitted.proposal.id,
            "request_id": submitted.request_id,
            "status": submitted.proposal.status.value,
        }
