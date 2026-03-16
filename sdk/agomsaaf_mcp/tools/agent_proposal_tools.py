"""
AgomSAAF MCP Tools - Agent Proposal Tools

WP-M3-05: Proposal-oriented MCP tools for the AI agent runtime.

Tools:
- create_agent_proposal
- get_agent_proposal
- approve_agent_proposal
- reject_agent_proposal
- execute_agent_proposal
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_agent_proposal_tools(server: FastMCP) -> None:
    """Register agent proposal MCP tools."""

    @server.tool()
    def create_agent_proposal(
        proposal_type: str,
        task_id: int | None = None,
        risk_level: str = "medium",
        approval_required: bool = True,
        proposal_payload: dict[str, Any] | None = None,
        approval_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new agent proposal for a high-risk action.

        Proposals go through a controlled lifecycle: create -> submit ->
        approve/reject -> execute. This ensures high-risk actions like
        signal creation, strategy binding, or trade execution are reviewed
        before taking effect.

        Args:
            proposal_type: Type of proposal (e.g., signal_create, trade_execute,
                          strategy_bind, config_write)
            task_id: Optional linked agent task ID
            risk_level: Risk assessment (low/medium/high/critical)
            approval_required: Whether human approval is needed (default true)
            proposal_payload: The action payload to execute on approval
            approval_reason: Rationale or description for the proposal

        Returns:
            Created proposal with request_id and status

        Example:
            >>> result = create_agent_proposal(
            ...     proposal_type="signal_create",
            ...     risk_level="high",
            ...     proposal_payload={"asset_code": "000001.SH", "direction": "long"}
            ... )
        """
        client = AgomSAAFClient()
        return client.agent_proposal.create_proposal(
            proposal_type=proposal_type,
            task_id=task_id,
            risk_level=risk_level,
            approval_required=approval_required,
            proposal_payload=proposal_payload,
            approval_reason=approval_reason,
        )

    @server.tool()
    def get_agent_proposal(proposal_id: int) -> dict[str, Any]:
        """
        Get details of an agent proposal.

        Args:
            proposal_id: ID of the proposal to retrieve

        Returns:
            Proposal details including status, risk level, and payload
        """
        client = AgomSAAFClient()
        return client.agent_proposal.get_proposal(proposal_id)

    @server.tool()
    def approve_agent_proposal(
        proposal_id: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Approve a submitted agent proposal.

        The proposal must be in 'submitted' status. After approval,
        it can be executed via execute_agent_proposal.

        Args:
            proposal_id: ID of the proposal to approve
            reason: Optional approval reason

        Returns:
            Updated proposal with approved status
        """
        client = AgomSAAFClient()
        return client.agent_proposal.approve_proposal(
            proposal_id=proposal_id,
            reason=reason,
        )

    @server.tool()
    def reject_agent_proposal(
        proposal_id: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Reject a submitted agent proposal.

        The proposal must be in 'submitted' status.

        Args:
            proposal_id: ID of the proposal to reject
            reason: Optional rejection reason

        Returns:
            Updated proposal with rejected status
        """
        client = AgomSAAFClient()
        return client.agent_proposal.reject_proposal(
            proposal_id=proposal_id,
            reason=reason,
        )

    @server.tool()
    def execute_agent_proposal(proposal_id: int) -> dict[str, Any]:
        """
        Execute an approved agent proposal.

        Runs pre-execution guardrail checks and creates an execution record.
        The proposal must be in 'approved' status. Guardrails will block
        execution if safety conditions are not met.

        Args:
            proposal_id: ID of the approved proposal to execute

        Returns:
            Execution result with proposal status, execution_record_id,
            and guardrail decision

        Example:
            >>> result = execute_agent_proposal(proposal_id=42)
            >>> print(result["execution_record_id"])
        """
        client = AgomSAAFClient()
        return client.agent_proposal.execute_proposal(proposal_id)
