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

    @server.tool()
    def check_pre_trade_risk(
        account_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        account_equity: float,
        total_position_value: float,
        cash_balance: float | None = None,
        current_symbol_position_value: float = 0.0,
    ) -> dict[str, Any]:
        """预览一笔拟交易是否会被集中风控中心拒绝。"""
        client = AgomTradeProClient()
        return client.risk_center.check_pre_trade(
            {
                "account_id": account_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "account_equity": account_equity,
                "total_position_value": total_position_value,
                "cash_balance": cash_balance,
                "current_symbol_position_value": current_symbol_position_value,
            }
        )

    @server.tool()
    def check_post_investment_risk(
        account_id: int,
        account_equity: float,
        positions: list[dict[str, Any]] | None = None,
        cash_balance: float | None = None,
        total_position_value: float | None = None,
        daily_pnl_pct: float | None = None,
        drawdown_pct: float | None = None,
    ) -> dict[str, Any]:
        """投后巡检一个账户当前持仓是否触碰集中风控约束。"""
        client = AgomTradeProClient()
        return client.risk_center.check_post_investment(
            {
                "account_id": account_id,
                "account_equity": account_equity,
                "cash_balance": cash_balance,
                "total_position_value": total_position_value,
                "daily_pnl_pct": daily_pnl_pct,
                "drawdown_pct": drawdown_pct,
                "positions": positions or [],
            }
        )
