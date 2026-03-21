"""AgomTradePro MCP Tools - Prompt 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_prompt_tools(server: FastMCP) -> None:
    @server.tool()
    def list_prompt_templates() -> list[dict[str, Any]]:
        client = AgomTradeProClient()
        return client.prompt.list_templates()

    @server.tool()
    def create_prompt_template(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.prompt.create_template(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def list_prompt_chains() -> list[dict[str, Any]]:
        client = AgomTradeProClient()
        return client.prompt.list_chains()

    @server.tool()
    def prompt_chat(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.prompt.chat(payload)

    @server.tool()
    def generate_prompt_report(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.prompt.generate_report(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def generate_prompt_signal(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        try:
            return client.prompt.generate_signal(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }
