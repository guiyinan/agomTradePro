"""AgomTradePro MCP Tools - Risk Center tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_risk_center_tools(server: FastMCP) -> None:
    @server.tool()
    def get_risk_floor() -> dict[str, Any]:
        """读取当前启用的全局风控底线。"""
        client = AgomTradeProClient()
        return client.risk_center.get_floor()

    @server.tool()
    def update_risk_floor(payload: dict[str, Any]) -> dict[str, Any]:
        """更新全局风控底线。调用方必须提供变更理由字段 reason。"""
        client = AgomTradeProClient()
        return client.risk_center.update_floor(payload)

    @server.tool()
    def list_risk_templates() -> list[dict[str, Any]]:
        """列出全局风险模板。"""
        client = AgomTradeProClient()
        return client.risk_center.list_templates()

    @server.tool()
    def upsert_account_risk_policy(payload: dict[str, Any]) -> dict[str, Any]:
        """创建或更新账户级风控策略。"""
        client = AgomTradeProClient()
        return client.risk_center.upsert_account_policy(payload)

    @server.tool()
    def get_account_risk_policy(account_id: int) -> dict[str, Any]:
        """按统一账户 ID 读取账户级风控策略。"""
        client = AgomTradeProClient()
        return client.risk_center.get_account_policy(account_id)

    @server.tool()
    def get_effective_risk_policy(account_id: int) -> dict[str, Any]:
        """解析账户最终生效风控策略，包含继承来源、底线和例外说明。"""
        client = AgomTradeProClient()
        return client.risk_center.get_effective_policy(account_id)

    @server.tool()
    def list_risk_exceptions(account_id: int | None = None) -> list[dict[str, Any]]:
        """列出管理员风控例外；可按账户过滤。"""
        client = AgomTradeProClient()
        return client.risk_center.list_exceptions(account_id=account_id)

    @server.tool()
    def create_risk_exception(payload: dict[str, Any]) -> dict[str, Any]:
        """创建有理由和过期时间的管理员风控例外。"""
        client = AgomTradeProClient()
        return client.risk_center.create_exception(payload)
