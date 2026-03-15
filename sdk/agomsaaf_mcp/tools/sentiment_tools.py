"""AgomSAAF MCP Tools - Sentiment 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_sentiment_tools(server: FastMCP) -> None:
    @server.tool()
    def analyze_sentiment(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.sentiment.analyze(payload)

    @server.tool()
    def batch_analyze_sentiment(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.sentiment.batch_analyze(payload)

    @server.tool()
    def get_sentiment_index(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        try:
            return client.sentiment.get_index(payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    @server.tool()
    def get_sentiment_recent(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.sentiment.index_recent(payload)

    @server.tool()
    def get_sentiment_health() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.sentiment.health()

    @server.tool()
    def clear_sentiment_cache() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.sentiment.clear_cache()
