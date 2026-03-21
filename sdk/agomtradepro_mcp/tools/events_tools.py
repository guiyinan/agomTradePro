"""AgomTradePro MCP Tools - Events 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_events_tools(server: FastMCP) -> None:
    @server.tool()
    def publish_event(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.events.publish(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def query_events(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.events.query(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def get_event_metrics() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.events.metrics()

    @server.tool()
    def get_event_bus_status() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.events.status()

    @server.tool()
    def replay_events(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.events.replay(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }
