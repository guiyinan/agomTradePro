"""AgomSAAF MCP Tools - Dashboard 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_dashboard_tools(server: FastMCP) -> None:
    @server.tool()
    def get_dashboard_summary_v1() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.summary_v1()

    @server.tool()
    def get_dashboard_regime_quadrant_v1() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.regime_quadrant_v1()

    @server.tool()
    def get_dashboard_equity_curve_v1() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.equity_curve_v1()

    @server.tool()
    def get_dashboard_signal_status_v1() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.signal_status_v1()

    @server.tool()
    def get_dashboard_positions() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.positions()

    @server.tool()
    def get_dashboard_allocation() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.dashboard.allocation()