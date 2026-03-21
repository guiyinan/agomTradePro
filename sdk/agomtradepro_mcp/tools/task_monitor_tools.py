"""AgomTradePro MCP Tools - Task Monitor 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_task_monitor_tools(server: FastMCP) -> None:
    @server.tool()
    def get_task_monitor_status(task_id: str) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.task_monitor.get_task_status(task_id)
        except Exception as exc:
            return {
                "success": False,
                "task_id": task_id,
                "error": str(exc),
            }

    @server.tool()
    def list_task_monitor_tasks() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.task_monitor.list_tasks()

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
