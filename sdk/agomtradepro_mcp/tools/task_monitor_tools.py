"""AgomTradePro MCP Tools - Task Monitor 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_task_monitor_tools(server: FastMCP) -> None:
    @server.tool()
    def get_task_monitor_status(task_id: str, diagnostics: bool = False) -> dict[str, Any]:
        """Read a task projection; diagnostics is restricted by API credentials."""

        client = AgomTradeProClient()
        try:
            return client.task_monitor.get_task_status(task_id, diagnostics=diagnostics)
        except Exception as exc:
            return {
                "success": False,
                "task_id": task_id,
                "error": str(exc),
            }

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
        client = AgomTradeProClient()
        if not task_name:
            return {
                "success": False,
                "error": "task_name is required",
            }
        try:
            return client.task_monitor.statistics(task_name=task_name, days=days)
        except Exception as exc:
            return {
                "success": False,
                "task_name": task_name,
                "days": days,
                "error": str(exc),
            }

    @server.tool()
    def get_task_monitor_dashboard() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.task_monitor.dashboard()

    @server.tool()
    def get_task_monitor_celery_health() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.task_monitor.celery_health()
