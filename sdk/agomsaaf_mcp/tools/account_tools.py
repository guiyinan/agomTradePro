"""
AgomSAAF MCP Tools - Account 账户管理工具

提供账户管理相关的 MCP 工具。
"""

from typing import Any

from mcp.server import Server

from agomsaaf import AgomSAAFClient


def register_account_tools(server: Server) -> None:
    """注册 Account 相关的 MCP 工具"""

    @server.tool()
    def list_portfolios(limit: int = 50) -> list[dict[str, Any]]:
        """
        获取投资组合列表

        Args:
            limit: 返回数量限制

        Returns:
            投资组合列表

        Example:
            >>> portfolios = list_portfolios()
        """
        client = AgomSAAFClient()
        portfolios = client.account.get_portfolios(limit=limit)

        return [
            {
                "id": p.id,
                "name": p.name,
                "total_value": p.total_value,
                "cash": p.cash,
                "positions_count": len(p.positions),
            }
            for p in portfolios
        ]

    @server.tool()
    def get_portfolio(portfolio_id: int) -> dict[str, Any]:
        """
        获取投资组合详情

        Args:
            portfolio_id: 组合 ID

        Returns:
            投资组合详情

        Example:
            >>> portfolio = get_portfolio(1)
        """
        client = AgomSAAFClient()
        portfolio = client.account.get_portfolio(portfolio_id)

        return {
            "id": portfolio.id,
            "name": portfolio.name,
            "total_value": portfolio.total_value,
            "cash": portfolio.cash,
            "positions": [
                {
                    "asset_code": p.asset_code,
                    "quantity": p.quantity,
                    "market_value": p.market_value,
                    "profit_loss": p.profit_loss,
                }
                for p in portfolio.positions
            ],
        }

    @server.tool()
    def get_positions(
        portfolio_id: int | None = None,
        asset_code: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取持仓列表

        Args:
            portfolio_id: 组合 ID 过滤（可选）
            asset_code: 资产代码过滤（可选）
            limit: 返回数量限制

        Returns:
            持仓列表

        Example:
            >>> positions = get_positions(portfolio_id=1)
        """
        client = AgomSAAFClient()
        positions = client.account.get_positions(portfolio_id, asset_code, limit)

        return [
            {
                "asset_code": p.asset_code,
                "quantity": p.quantity,
                "avg_cost": p.avg_cost,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "profit_loss": p.profit_loss,
            }
            for p in positions
        ]

    @server.tool()
    def create_position(
        portfolio_id: int,
        asset_code: str,
        quantity: float,
        price: float,
    ) -> dict[str, Any]:
        """
        创建持仓

        Args:
            portfolio_id: 组合 ID
            asset_code: 资产代码
            quantity: 数量
            price: 成交价格

        Returns:
            创建的持仓

        Example:
            >>> position = create_position(
            ...     portfolio_id=1,
            ...     asset_code="000001.SH",
            ...     quantity=1000,
            ...     price=10.5
            ... )
        """
        client = AgomSAAFClient()
        position = client.account.create_position(portfolio_id, asset_code, quantity, price)

        return {
            "asset_code": position.asset_code,
            "quantity": position.quantity,
            "avg_cost": position.avg_cost,
            "current_price": position.current_price,
            "market_value": position.market_value,
        }
