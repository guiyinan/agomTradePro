"""AgomSAAF MCP Tools - Decision Rhythm 工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_decision_rhythm_tools(server: FastMCP) -> None:
    @server.tool()
    def list_decision_quotas() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.decision_rhythm.list_quotas()

    @server.tool()
    def list_decision_requests() -> list[dict[str, Any]]:
        client = AgomSAAFClient()
        return client.decision_rhythm.list_requests()

    @server.tool()
    def submit_decision_request(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.decision_rhythm.submit(payload)

    @server.tool()
    def submit_batch_decision_request(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.decision_rhythm.submit_batch(payload)

    @server.tool()
    def get_decision_rhythm_summary(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.decision_rhythm.summary(payload)

    @server.tool()
    def reset_decision_quota(payload: dict[str, Any]) -> dict[str, Any]:
        client = AgomSAAFClient()
        return client.decision_rhythm.reset_quota(payload)