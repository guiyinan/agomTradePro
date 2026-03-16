"""
AgomSAAF MCP Tools - Agent Task Tools

WP-M2-04: Task-oriented MCP tools for the AI agent runtime.

Tools:
- start_research_task
- start_monitoring_task
- start_decision_task
- start_execution_task
- start_ops_task
- resume_agent_task
- cancel_agent_task
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_agent_task_tools(server: FastMCP) -> None:
    """Register agent task MCP tools."""

    def _start_task(
        domain: str,
        task_type: str,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Shared helper: create task and attach context snapshot reference."""
        client = AgomSAAFClient()

        # Create the task
        result = client.agent_runtime.create_task(
            task_domain=domain,
            task_type=task_type,
            input_payload=input_payload or {},
        )

        # Fetch linked context snapshot
        try:
            context = client.agent_context.get_context_snapshot(domain)
            result["context_snapshot"] = {
                "domain": context.get("domain"),
                "generated_at": context.get("generated_at"),
                "regime_summary": context.get("regime_summary"),
                "policy_summary": context.get("policy_summary"),
            }
        except Exception:
            result["context_snapshot"] = {"status": "unavailable"}

        return result

    @server.tool()
    def start_research_task(
        task_type: str = "macro_portfolio_review",
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Start a research task for macro analysis, portfolio review, or factor research.

        Creates an agent task in the 'research' domain and returns the task
        together with a context snapshot including regime, policy, and signals.

        Args:
            task_type: Research task subtype (e.g., macro_portfolio_review,
                      factor_analysis, sector_scan)
            input_payload: Additional parameters for the research task

        Returns:
            Created task with context snapshot reference

        Example:
            >>> result = start_research_task(
            ...     task_type="macro_portfolio_review",
            ...     input_payload={"focus": "regime_change"}
            ... )
        """
        return _start_task("research", task_type, input_payload)

    @server.tool()
    def start_monitoring_task(
        task_type: str = "price_alert_check",
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Start a monitoring task for price alerts, sentiment tracking, or data quality.

        Creates an agent task in the 'monitoring' domain and returns the task
        together with a context snapshot including alerts and freshness data.

        Args:
            task_type: Monitoring task subtype (e.g., price_alert_check,
                      sentiment_scan, data_freshness_check)
            input_payload: Additional parameters for the monitoring task

        Returns:
            Created task with context snapshot reference
        """
        return _start_task("monitoring", task_type, input_payload)

    @server.tool()
    def start_decision_task(
        task_type: str = "signal_approval",
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Start a decision task for signal approval, quota check, or rebalance proposal.

        Creates an agent task in the 'decision' domain and returns the task
        together with a context snapshot including quotas and pending approvals.

        Args:
            task_type: Decision task subtype (e.g., signal_approval,
                      rebalance_proposal, position_sizing)
            input_payload: Additional parameters for the decision task

        Returns:
            Created task with context snapshot reference
        """
        return _start_task("decision", task_type, input_payload)

    @server.tool()
    def start_execution_task(
        task_type: str = "trade_execution",
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Start an execution task for trade execution, position adjustment, or hedging.

        Creates an agent task in the 'execution' domain and returns the task
        together with a context snapshot including positions and accounts.

        Args:
            task_type: Execution task subtype (e.g., trade_execution,
                      position_adjustment, hedge_execution)
            input_payload: Additional parameters for the execution task

        Returns:
            Created task with context snapshot reference
        """
        return _start_task("execution", task_type, input_payload)

    @server.tool()
    def start_ops_task(
        task_type: str = "system_health_check",
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Start an ops task for system health, data sync, or audit review.

        Creates an agent task in the 'ops' domain and returns the task
        together with a context snapshot including event bus and provider status.

        Args:
            task_type: Ops task subtype (e.g., system_health_check,
                      data_sync, audit_review)
            input_payload: Additional parameters for the ops task

        Returns:
            Created task with context snapshot reference
        """
        return _start_task("ops", task_type, input_payload)

    @server.tool()
    def resume_agent_task(
        task_id: int,
        target_status: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Resume an agent task that is in failed or needs_human state.

        Args:
            task_id: ID of the task to resume
            target_status: Target status (optional, defaults based on current state)
            reason: Reason for resuming the task

        Returns:
            Updated task with timeline event ID

        Example:
            >>> result = resume_agent_task(task_id=42, reason="Fixed data issue")
        """
        client = AgomSAAFClient()
        return client.agent_runtime.resume_task(
            task_id=task_id,
            target_status=target_status,
            reason=reason,
        )

    @server.tool()
    def cancel_agent_task(
        task_id: int,
        reason: str = "Cancelled via MCP",
    ) -> dict[str, Any]:
        """
        Cancel an active agent task.

        Args:
            task_id: ID of the task to cancel
            reason: Reason for cancellation

        Returns:
            Cancelled task with timeline event ID

        Example:
            >>> result = cancel_agent_task(task_id=42, reason="No longer needed")
        """
        client = AgomSAAFClient()
        return client.agent_runtime.cancel_task(
            task_id=task_id,
            reason=reason,
        )
