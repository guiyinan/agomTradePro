"""AgomSAAF MCP Tools - Task Monitor 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_task_monitor_tools(server: FastMCP) -> None:
    @server.tool()
    def get_task_monitor_status(task_id: str) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.task_monitor.get_task_status(task_id)

    @server.tool()
    def list_task_monitor_tasks() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.task_monitor.list_tasks()

    @server.tool()
    def get_task_monitor_statistics() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.task_monitor.statistics()

    @server.tool()
    def get_task_monitor_dashboard() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.task_monitor.dashboard()

    @server.tool()
    def get_task_monitor_celery_health() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.task_monitor.celery_health()