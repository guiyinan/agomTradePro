"""AgomSAAF MCP Tools - Events 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_events_tools(server: FastMCP) -> None:
    @server.tool()
    def publish_event(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.events.publish(payload)

    @server.tool()
    def query_events(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.events.query(payload)

    @server.tool()
    def get_event_metrics() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.events.metrics()

    @server.tool()
    def get_event_bus_status() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.events.status()

    @server.tool()
    def replay_events(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.events.replay(payload)