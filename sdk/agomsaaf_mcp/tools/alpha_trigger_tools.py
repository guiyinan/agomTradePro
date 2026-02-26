"""AgomSAAF MCP Tools - Alpha Trigger 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_alpha_trigger_tools(server: FastMCP) -> None:
    @server.tool()
    def list_alpha_triggers() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.alpha_trigger.list_triggers()

    @server.tool()
    def create_alpha_trigger(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.alpha_trigger.create_trigger(payload)

    @server.tool()
    def evaluate_alpha_trigger(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.alpha_trigger.evaluate(payload)

    @server.tool()
    def check_alpha_trigger_invalidation(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.alpha_trigger.check_invalidation(payload)

    @server.tool()
    def generate_alpha_candidate(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.alpha_trigger.generate_candidate(payload)

    @server.tool()
    def alpha_trigger_performance(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.alpha_trigger.performance(payload)