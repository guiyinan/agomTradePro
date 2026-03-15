"""AgomSAAF MCP Tools - Filter 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_filter_tools(server: FastMCP) -> None:
    @server.tool()
    def list_filters() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.filter.list_filters()

    @server.tool()
    def get_filter(filter_id: int | None = None, indicator_code: str | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.filter.get_filter(filter_id=filter_id, indicator_code=indicator_code)

    @server.tool()
    def create_filter(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.filter.create_filter(payload)

    @server.tool()
    def update_filter(filter_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.filter.update_filter(filter_id, payload)

    @server.tool()
    def delete_filter(filter_id: int) -> dict[str, Any]:
        client = AgomSAAFClient()
        client.filter.delete_filter(filter_id)
        return {"success": True, "filter_id": filter_id}

    @server.tool()
    def get_filter_health() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.filter.health()
