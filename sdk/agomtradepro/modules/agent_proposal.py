"""
AgomTradePro SDK - Agent Proposal Module

WP-M3-04: Provides proposal lifecycle operations.

Public methods:
- create_proposal
- get_proposal
- submit_proposal_for_approval
- approve_proposal
- reject_proposal
- execute_proposal
"""

from typing import Any, Dict, Optional

from .base import BaseModule


class AgentProposalModule(BaseModule):
    """
    Agent Proposal module.

    Manages AI agent proposal lifecycle: create, submit, approve, reject, execute.
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/agent-runtime")

    def create_proposal(
        self,
        proposal_type: str,
        task_id: int | None = None,
        risk_level: str = "medium",
        approval_required: bool = True,
        proposal_payload: dict[str, Any] | None = None,
        approval_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new proposal, optionally linked to a task.

        Args:
            proposal_type: Type of proposal (e.g., signal_create, trade_execute)
            task_id: Optional linked task ID
            risk_level: Risk level (low/medium/high/critical)
            approval_required: Whether approval is required
            proposal_payload: Execution payload
            approval_reason: Optional reason/description

        Returns:
            Dict with request_id and created proposal details
        """
        body: dict[str, Any] = {
            "proposal_type": proposal_type,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "proposal_payload": proposal_payload or {},
        }
        if task_id is not None:
            body["task_id"] = task_id
        if approval_reason is not None:
            body["approval_reason"] = approval_reason
        return self._post("proposals/", json=body)

    def get_proposal(self, proposal_id: int) -> dict[str, Any]:
        """
        Get a single proposal by ID.

        Args:
            proposal_id: Proposal ID

        Returns:
            Dict with request_id and proposal details
        """
        return self._get(f"proposals/{proposal_id}/")

    def submit_proposal_for_approval(
        self,
        proposal_id: int,
    ) -> dict[str, Any]:
        """
        Submit a proposal for approval (runs pre-approval guardrails).

        Args:
            proposal_id: Proposal ID

        Returns:
            Dict with request_id, proposal, and guardrail_decision
        """
        return self._post(f"proposals/{proposal_id}/submit-approval/")

    def approve_proposal(
        self,
        proposal_id: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Approve a submitted proposal.

        Args:
            proposal_id: Proposal ID
            reason: Approval reason

        Returns:
            Dict with request_id and approved proposal
        """
        body: dict[str, Any] = {}
        if reason is not None:
            body["reason"] = reason
        return self._post(f"proposals/{proposal_id}/approve/", json=body)

    def reject_proposal(
        self,
        proposal_id: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Reject a submitted proposal.

        Args:
            proposal_id: Proposal ID
            reason: Rejection reason

        Returns:
            Dict with request_id and rejected proposal
        """
        body: dict[str, Any] = {}
        if reason is not None:
            body["reason"] = reason
        return self._post(f"proposals/{proposal_id}/reject/", json=body)

    def execute_proposal(
        self,
        proposal_id: int,
    ) -> dict[str, Any]:
        """
        Execute an approved proposal (runs pre-execution guardrails).

        Args:
            proposal_id: Proposal ID

        Returns:
            Dict with request_id, proposal, execution_record_id, guardrail_decision
        """
        return self._post(f"proposals/{proposal_id}/execute/")
