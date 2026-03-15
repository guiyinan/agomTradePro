"""AgomSAAF MCP Tools - AI Provider 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_ai_provider_tools(server: FastMCP) -> None:
    @server.tool()
    def list_ai_providers() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        payload = client.ai_provider.list_providers()
        return payload if isinstance(payload, list) else []

    @server.tool()
    def get_ai_provider(provider_id: int) -> dict[str, Any]:
        client = AgomSAAFClient()
        try:
            return client.ai_provider.get_provider(provider_id)
        except Exception as exc:
            return {
                "success": False,
                "provider_id": provider_id,
                "error": str(exc),
            }

    @server.tool()
    def create_ai_provider(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.ai_provider.create_provider(payload)

    @server.tool()
    def update_ai_provider(provider_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.ai_provider.update_provider(provider_id, payload)

    @server.tool()
    def toggle_ai_provider(provider_id: int) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.ai_provider.toggle_provider(provider_id)

    @server.tool()
    def list_ai_usage_logs(provider_id: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.ai_provider.list_usage_logs(provider_id=provider_id, status=status)
