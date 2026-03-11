"""AgomSAAF MCP Tools - Config Center tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_config_center_tools(server: FastMCP) -> None:
    @server.tool()
    def list_config_capabilities() -> list[dict[str, Any]]:
        """列出系统当前支持统一发现的配置能力清单。"""
        client = AgomSAAFClient()
        return client.config_center.list_capabilities()

    @server.tool()
    def get_config_center_snapshot() -> dict[str, Any]:
        """获取当前配置中心聚合摘要。"""
        client = AgomSAAFClient()
        return client.config_center.get_snapshot()
