from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Account 账户管理模块

提供账户和持仓管理相关的 API 操作。
"""

from typing import Any, Optional

from .base import BaseModule
from ..types import Portfolio, Position


class AccountModule(BaseModule):
    """
    账户管理模块

    提供投资组合查询、持仓管理等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Account 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/account")

    def get_portfolios(
        self,
        limit: int = 100,
    ) -> list[Portfolio]:
        """
        获取投资组合列表

        Args:
            limit: 返回数量限制

        Returns:
            投资组合列表

        Example:
            >>> client = AgomSAAFClient()
            >>> portfolios = client.account.get_portfolios()
            >>> for portfolio in portfolios:
            ...     print(f"{portfolio.name}: {portfolio.total_value:.2f}")
        """
        params: dict[str, Any] = {"limit": limit}
        response = self._get("portfolios/", params=params)
        results = response.get("results", response)
        return [self._parse_portfolio(item) for item in results]

    def get_portfolio(self, portfolio_id: int) -> Portfolio:
        """
        获取单个投资组合详情

        Args:
            portfolio_id: 组合 ID

        Returns:
            投资组合详情

        Raises:
            NotFoundError: 当组合不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> portfolio = client.account.get_portfolio(1)
            >>> print(f"组合名称: {portfolio.name}")
            >>> print(f"总市值: {portfolio.total_value:.2f}")
        """
        response = self._get(f"portfolios/{portfolio_id}/")
        return self._parse_portfolio(response)

    def get_positions(
        self,
        portfolio_id: Optional[int] = None,
        asset_code: Optional[str] = None,
        limit: int = 100,
    ) -> list[Position]:
        """
        获取持仓列表

        Args:
            portfolio_id: 组合 ID 过滤（可选）
            asset_code: 资产代码过滤（可选）
            limit: 返回数量限制

        Returns:
            持仓列表

        Example:
            >>> client = AgomSAAFClient()
            >>> positions = client.account.get_positions(portfolio_id=1)
            >>> for position in positions:
            ...     print(f"{position.asset_code}: {position.quantity}")
        """
        params: dict[str, Any] = {"limit": limit}

        if portfolio_id is not None:
            params["portfolio_id"] = portfolio_id
        if asset_code is not None:
            params["asset_code"] = asset_code

        response = self._get("positions/", params=params)
        results = response.get("results", response)
        return [self._parse_position(item) for item in results]

    def get_position(self, position_id: int) -> Position:
        """
        获取单个持仓详情

        Args:
            position_id: 持仓 ID

        Returns:
            持仓详情

        Raises:
            NotFoundError: 当持仓不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> position = client.account.get_position(123)
            >>> print(f"资产: {position.asset_code}")
            >>> print(f"数量: {position.quantity}")
        """
        response = self._get(f"positions/{position_id}/")
        return self._parse_position(response)

    def create_position(
        self,
        portfolio_id: int,
        asset_code: str,
        quantity: float,
        price: float,
    ) -> Position:
        """
        创建持仓

        Args:
            portfolio_id: 组合 ID
            asset_code: 资产代码
            quantity: 数量
            price: 成交价格

        Returns:
            创建的持仓

        Raises:
            ValidationError: 当参数验证失败时
            NotFoundError: 当组合不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> position = client.account.create_position(
            ...     portfolio_id=1,
            ...     asset_code="000001.SH",
            ...     quantity=1000,
            ...     price=10.5
            ... )
            >>> print(f"持仓已创建: {position.id}")
        """
        data: dict[str, Any] = {
            "portfolio_id": portfolio_id,
            "asset_code": asset_code,
            "quantity": quantity,
            "price": price,
        }

        response = self._post("positions/", json=data)
        return self._parse_position(response)

    def update_position(
        self,
        position_id: int,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
    ) -> Position:
        """
        更新持仓

        Args:
            position_id: 持仓 ID
            quantity: 新的数量（可选）
            price: 新的价格（可选）

        Returns:
            更新后的持仓

        Raises:
            NotFoundError: 当持仓不存在时
            ValidationError: 当参数验证失败时

        Example:
            >>> client = AgomSAAFClient()
            >>> position = client.account.update_position(
            ...     position_id=123,
            ...     quantity=2000
            ... )
        """
        data: dict[str, Any] = {}
        if quantity is not None:
            data["quantity"] = quantity
        if price is not None:
            data["price"] = price

        response = self._put(f"positions/{position_id}/", json=data)
        return self._parse_position(response)

    def delete_position(self, position_id: int) -> None:
        """
        删除持仓

        Args:
            position_id: 持仓 ID

        Raises:
            NotFoundError: 当持仓不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> client.account.delete_position(123)
            >>> print("持仓已删除")
        """
        self._delete(f"positions/{position_id}/")

    def _parse_portfolio(self, data: dict[str, Any]) -> Portfolio:
        """
        解析投资组合数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            Portfolio 对象
        """
        # 解析持仓列表
        positions = []
        for pos_data in data.get("positions", []):
            positions.append(self._parse_position(pos_data))

        return Portfolio(
            id=data["id"],
            name=data["name"],
            total_value=data["total_value"],
            cash=data["cash"],
            positions=positions,
        )

    def _parse_position(self, data: dict[str, Any]) -> Position:
        """
        解析持仓数据

        Args:
            data: API 返回的 JSON 数据

        Returns:
            Position 对象
        """
        return Position(
            asset_code=data["asset_code"],
            quantity=data["quantity"],
            avg_cost=data["avg_cost"],
            current_price=data["current_price"],
            market_value=data["market_value"],
            profit_loss=data["profit_loss"],
        )
