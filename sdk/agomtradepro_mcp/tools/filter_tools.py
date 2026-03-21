"""AgomTradePro MCP Tools - Filter 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_filter_tools(server: FastMCP) -> None:
    @server.tool()
    def list_filters() -> list[dict[str, Any]]:
        client = AgomTradeProClient()
        return client.filter.list_filters()

    @server.tool()
    def get_filter(filter_id: int | None = None, indicator_code: str | None = None) -> dict[str, Any]:
        client = AgomTradeProClient()
        if indicator_code is not None:
            return client.filter.get_filter(indicator_code=indicator_code)
        return client.filter.get_filter(filter_id)

    @server.tool()
    def create_filter(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.filter.create_filter(payload)
        except Exception as exc:
            return {"success": False, "error": str(exc), "payload": payload}

    @server.tool()
    def update_filter(filter_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.filter.update_filter(filter_id, payload)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filter_id": filter_id, "payload": payload}

    @server.tool()
    def delete_filter(filter_id: int) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            client.filter.delete_filter(filter_id)
            return {"success": True, "filter_id": filter_id}
        except Exception as exc:
            return {"success": False, "error": str(exc), "filter_id": filter_id}

    @server.tool()
    def get_filter_health() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.filter.health()
