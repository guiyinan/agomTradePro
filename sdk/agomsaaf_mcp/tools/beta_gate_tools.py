"""AgomSAAF MCP Tools - Beta Gate 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_beta_gate_tools(server: FastMCP) -> None:
    @server.tool()
    def list_beta_gate_configs() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.beta_gate.list_configs()

    @server.tool()
    def create_beta_gate_config(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.beta_gate.create_config(payload)

    @server.tool()
    def test_beta_gate(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.beta_gate.test_gate(payload)

    @server.tool()
    def compare_beta_gate_version(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.beta_gate.version_compare(payload)

    @server.tool()
    def rollback_beta_gate_config(config_id: str) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.beta_gate.rollback_config(config_id)