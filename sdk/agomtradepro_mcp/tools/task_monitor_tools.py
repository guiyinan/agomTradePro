"""AgomTradePro MCP Tools - Task Monitor 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_task_monitor_tools(server: FastMCP) -> None:
    """Register Task Monitor reads backed by the configured SDK client."""

    @server.tool()
    def get_task_monitor_status(task_id: str, diagnostics: bool = False) -> dict[str, Any]:
        """Read a task projection with diagnostics restricted by API credentials."""

        client = AgomTradeProClient()
        return client.task_monitor.get_task_status(task_id, diagnostics=diagnostics)

    @server.tool()
    def list_task_monitor_tasks(
        task_name: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        failures_only: bool = False,
        diagnostics: bool = False,
    ) -> dict[str, Any]:
        """List task projections with optional filters and protected diagnostics."""

        client = AgomTradeProClient()
        return client.task_monitor.list_tasks(
            task_name=task_name,
            status=status,
            limit=limit,
            failures_only=failures_only,
            diagnostics=diagnostics,
        )

    @server.tool()
    def get_task_monitor_statistics(task_name: str | None = None, days: int = 7) -> dict[str, Any]:
        """Read aggregate execution statistics for the selected task."""
        client = AgomTradeProClient()
        return client.task_monitor.statistics(task_name=task_name, days=days)

    @server.tool()
    def get_task_monitor_dashboard() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.task_monitor.dashboard()

    @server.tool()
    def get_task_monitor_celery_health() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.task_monitor.celery_health()
