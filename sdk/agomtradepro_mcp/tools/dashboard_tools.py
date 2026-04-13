"""AgomTradePro MCP Tools - Dashboard 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_dashboard_tools(server: FastMCP) -> None:
    @server.tool()
    def get_dashboard_summary_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.summary_v1()

    @server.tool()
    def get_dashboard_regime_quadrant_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.regime_quadrant_v1()

    @server.tool()
    def get_dashboard_equity_curve_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.equity_curve_v1()

    @server.tool()
    def get_dashboard_signal_status_v1() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.signal_status_v1()

    @server.tool()
    def get_dashboard_alpha_decision_chain_v1(
        top_n: int = 10,
        max_candidates: int = 5,
        max_pending: int = 10,
    ) -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.alpha_decision_chain_v1(
            top_n=top_n,
            max_candidates=max_candidates,
            max_pending=max_pending,
        )

    @server.tool()
    def get_dashboard_positions() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.positions()

    @server.tool()
    def get_dashboard_allocation() -> dict[str, Any]:
        client = AgomTradeProClient()
        return client.dashboard.allocation()
