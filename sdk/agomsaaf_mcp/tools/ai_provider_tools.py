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
        normalized = dict(payload)
        if "model_name" in normalized and "default_model" not in normalized:
            normalized["default_model"] = normalized.pop("model_name")
        provider_type = str(normalized.get("provider_type", "")).strip().lower()
        if not normalized.get("base_url"):
            default_base_urls = {
                "openai": "https://api.openai.com/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "anthropic": "https://api.anthropic.com",
            }
            normalized["base_url"] = default_base_urls.get(provider_type, "https://api.openai.com/v1")
        try:
            return client.ai_provider.create_provider(normalized)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": {
                    k: v for k, v in normalized.items() if k != "api_key"
                },
            }

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
