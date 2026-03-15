"""AgomSAAF MCP Tools - Audit 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_audit_tools(server: FastMCP) -> None:
    @server.tool()
    def get_audit_summary(
        backtest_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.audit.get_summary(
            backtest_id=backtest_id,
            start_date=start_date,
            end_date=end_date,
        )

    @server.tool()
    def generate_audit_report(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.audit.generate_report(payload)

    @server.tool()
    def run_audit_validation(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.audit.run_validation(payload)

    @server.tool()
    def validate_all_indicators() -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.audit.validate_all_indicators()

    @server.tool()
    def update_audit_threshold(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.audit.update_threshold(payload)
