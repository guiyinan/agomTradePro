"""AgomTradePro MCP Tools - Alpha Trigger 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_alpha_trigger_tools(server: FastMCP) -> None:
    @server.tool()
    def list_alpha_triggers() -> list[dict[str, Any]]:
        client = AgomTradeProClient()
        try:
            return client.alpha_trigger.list_triggers()
        except Exception:
            return []

    @server.tool()
    def create_alpha_trigger(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.alpha_trigger.create_trigger(payload)

    @server.tool()
    def evaluate_alpha_trigger(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.alpha_trigger.evaluate(payload)

    @server.tool()
    def check_alpha_trigger_invalidation(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.alpha_trigger.check_invalidation(payload)

    @server.tool()
    def generate_alpha_candidate(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.alpha_trigger.generate_candidate(payload)

    @server.tool()
    def alpha_trigger_performance(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomTradeProClient()
        result = client.alpha_trigger.performance(payload)
        if isinstance(result, list):
            return {
                "data": result,
                "summary": {},
            }
        return result

    @server.tool()
    def list_alpha_candidates() -> list[dict[str, Any]]:
        client = AgomTradeProClient()
        return client.alpha_trigger.list_candidates()

    @server.tool()
    def get_alpha_candidate(candidate_id: str) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.alpha_trigger.get_candidate(candidate_id)

    @server.tool()
    def update_alpha_candidate_status(candidate_id: str, status: str) -> dict[str, Any]:
        """
        更新 Alpha 候选状态。

        status 支持：WATCH/CANDIDATE/ACTIONABLE/EXECUTED/CANCELLED
        """
        client = AgomTradeProClient()
        return client.alpha_trigger.update_candidate_status(candidate_id, status)
