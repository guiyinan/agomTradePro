"""AgomSAAF MCP Tools - Prompt 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_prompt_tools(server: FastMCP) -> None:
    @server.tool()
    def list_prompt_templates() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.prompt.list_templates()

    @server.tool()
    def create_prompt_template(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.prompt.create_template(payload)

    @server.tool()
    def list_prompt_chains() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.prompt.list_chains()

    @server.tool()
    def prompt_chat(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.prompt.chat(payload)

    @server.tool()
    def generate_prompt_report(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.prompt.generate_report(payload)

    @server.tool()
    def generate_prompt_signal(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.prompt.generate_signal(payload)