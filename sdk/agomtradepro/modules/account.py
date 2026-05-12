"""
AgomTradePro SDK - Account 账户管理模块

提供账户和持仓管理相关的 API 操作。
"""

from typing import Any

from ..types import Portfolio, Position
from .base import BaseModule


class AccountModule(BaseModule):
    """
    账户管理模块

    提供统一账户查询与旧 portfolio 兼容接口。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Account 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        # Canonical account endpoints are served under /api/account/*.
        super().__init__(client, "/api/account")

    def list_accounts(
        self,
        account_type: str | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取统一账户列表。

        Args:
            account_type: 可选，`real` 或 `simulated`
            active_only: 是否仅返回活跃账户
            limit: 返回数量限制
        """
        params: dict[str, Any] = {"active_only": active_only, "limit": limit}
        if account_type is not None:
            params["account_type"] = account_type
        response = self._client.get("/api/account/accounts/", params=params)
        if isinstance(response, dict):
            return response.get("accounts", [])
        return response

    def get_account(self, account_id: int) -> dict[str, Any]:
        """
        获取统一账户详情。

        Args:
            account_id: 统一账户 ID
        """
        response = self._client.get(f"/api/account/accounts/{account_id}/")
        if isinstance(response, dict):
            return response.get("account", response)
        return response

    def create_account(
        self,
        name: str,
        initial_capital: float,
        account_type: str = "simulated",
        max_position_pct: float = 20.0,
        stop_loss_pct: float | None = None,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
    ) -> dict[str, Any]:
        """
        创建统一账户。

        Args:
            name: 账户名称
            initial_capital: 初始资金
            account_type: 账户类型，`real` 或 `simulated`
        """
        payload: dict[str, Any] = {
            "account_name": name,
            "account_type": account_type,
            "initial_capital": initial_capital,
            "max_position_pct": max_position_pct,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
        }
        if stop_loss_pct is not None:
            payload["stop_loss_pct"] = stop_loss_pct
        response = self._client.post("/api/account/accounts/", json=payload)
        if isinstance(response, dict):
            return response.get("account", response)
        return response

    def get_account_positions(
        self,
        account_id: int,
        asset_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取统一账户持仓列表。
        """
        response = self._client.get(f"/api/account/accounts/{account_id}/positions/")
        if isinstance(response, dict):
            rows = response.get("positions", [])
        else:
            rows = response
        if asset_code is not None:
            rows = [row for row in rows if row.get("asset_code") == asset_code]
        return rows

    def get_account_performance(
        self,
        account_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取统一账户绩效。

        如传入 start_date/end_date，则调用区间业绩报告；
        否则调用基础绩效摘要接口。
        """
        if start_date and end_date:
            return self._client.get(
                f"/api/account/accounts/{account_id}/performance-report/",
                params={"start_date": start_date, "end_date": end_date},
            )
        response = self._client.get(f"/api/account/accounts/{account_id}/performance/")
        if isinstance(response, dict):
            return response.get("performance", response)
        return response

    def get_portfolios(
        self,
        limit: int = 100,
    ) -> list[Portfolio]:
        """
        获取投资组合列表（兼容接口）。

        Args:
            limit: 返回数量限制

        Returns:
            投资组合列表

        Example:
            >>> client = AgomTradeProClient()
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
        获取单个投资组合详情（兼容接口）。

        Args:
            portfolio_id: 组合 ID

        Returns:
            投资组合详情

        Raises:
            NotFoundError: 当组合不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> portfolio = client.account.get_portfolio(1)
            >>> print(f"组合名称: {portfolio.name}")
            >>> print(f"总市值: {portfolio.total_value:.2f}")
        """
        response = self._get(f"portfolios/{portfolio_id}/")
        return self._parse_portfolio(response)

    def get_positions(
        self,
        portfolio_id: int | None = None,
        asset_code: str | None = None,
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
            >>> client = AgomTradeProClient()
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
            >>> client = AgomTradeProClient()
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
            >>> client = AgomTradeProClient()
            >>> position = client.account.create_position(
            ...     portfolio_id=1,
            ...     asset_code="000001.SH",
            ...     quantity=1000,
            ...     price=10.5
            ... )
            >>> print(f"持仓已创建: {position.id}")
        """
        # Keep SDK API stable (quantity/price), map to backend fields.
        data: dict[str, Any] = {
            "portfolio": portfolio_id,
            "asset_code": asset_code,
            "shares": quantity,
            "avg_cost": price,
            "current_price": price,
            "source": "manual",
            "asset_class": "equity",
            "region": "CN",
            "cross_border": "domestic",
        }

        response = self._post("positions/", json=data)
        return self._parse_position(response)

    def update_position(
        self,
        position_id: int,
        quantity: float | None = None,
        price: float | None = None,
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
            >>> client = AgomTradeProClient()
            >>> position = client.account.update_position(
            ...     position_id=123,
            ...     quantity=2000
            ... )
        """
        data: dict[str, Any] = {}
        if quantity is not None:
            data["shares"] = quantity
        if price is not None:
            data["current_price"] = price

        response = self._patch(f"positions/{position_id}/", json=data)
        return self._parse_position(response)

    def delete_position(self, position_id: int) -> None:
        """
        删除持仓

        Args:
            position_id: 持仓 ID

        Raises:
            NotFoundError: 当持仓不存在时

        Example:
            >>> client = AgomTradeProClient()
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
            id=int(data["id"]),
            name=str(data["name"]),
            total_value=self._to_float(data.get("total_value"), default=0.0),
            cash=self._to_float(data.get("cash"), default=0.0),
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
        quantity_raw = data.get("quantity", data.get("shares", 0))
        profit_loss_raw = data.get("profit_loss", data.get("unrealized_pnl", 0))
        current_price_raw = data.get("current_price")
        if current_price_raw is None:
            current_price_raw = data.get("avg_cost", 0)

        return Position(
            asset_code=str(data.get("asset_code", "")),
            quantity=self._to_float(quantity_raw, default=0.0),
            avg_cost=self._to_float(data.get("avg_cost"), default=0.0),
            current_price=self._to_float(current_price_raw, default=0.0),
            market_value=self._to_float(data.get("market_value"), default=0.0),
            profit_loss=self._to_float(profit_loss_raw, default=0.0),
        )

    # ==================== Trading Cost Config ====================

    def get_trading_cost_configs(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        获取交易费率配置列表

        Args:
            limit: 返回数量限制

        Returns:
            费率配置列表
        """
        response = self._get("trading-cost-configs/", params={"limit": limit})
        results = response.get("results", response)
        if isinstance(results, list):
            return results
        return []

    def get_trading_cost_config(self, config_id: int) -> dict[str, Any]:
        """
        获取单个交易费率配置详情

        Args:
            config_id: 配置 ID

        Returns:
            费率配置详情
        """
        return self._get(f"trading-cost-configs/{config_id}/")

    def create_trading_cost_config(
        self,
        portfolio_id: int,
        commission_rate: float = 0.00025,
        min_commission: float = 5.0,
        stamp_duty_rate: float = 0.001,
        transfer_fee_rate: float = 0.00002,
    ) -> dict[str, Any]:
        """
        创建交易费率配置

        Args:
            portfolio_id: 投资组合 ID
            commission_rate: 佣金率（默认万2.5）
            min_commission: 最低佣金（元）
            stamp_duty_rate: 印花税率（默认千1）
            transfer_fee_rate: 过户费率（默认万0.2）

        Returns:
            创建的费率配置
        """
        data: dict[str, Any] = {
            "portfolio": portfolio_id,
            "commission_rate": commission_rate,
            "min_commission": min_commission,
            "stamp_duty_rate": stamp_duty_rate,
            "transfer_fee_rate": transfer_fee_rate,
        }
        return self._post("trading-cost-configs/", json=data)

    def update_trading_cost_config(
        self,
        config_id: int,
        commission_rate: float | None = None,
        min_commission: float | None = None,
        stamp_duty_rate: float | None = None,
        transfer_fee_rate: float | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        """
        更新交易费率配置

        Args:
            config_id: 配置 ID
            commission_rate: 佣金率
            min_commission: 最低佣金
            stamp_duty_rate: 印花税率
            transfer_fee_rate: 过户费率
            is_active: 是否启用

        Returns:
            更新后的费率配置
        """
        data: dict[str, Any] = {}
        if commission_rate is not None:
            data["commission_rate"] = commission_rate
        if min_commission is not None:
            data["min_commission"] = min_commission
        if stamp_duty_rate is not None:
            data["stamp_duty_rate"] = stamp_duty_rate
        if transfer_fee_rate is not None:
            data["transfer_fee_rate"] = transfer_fee_rate
        if is_active is not None:
            data["is_active"] = is_active
        return self._patch(f"trading-cost-configs/{config_id}/", json=data)

    def delete_trading_cost_config(self, config_id: int) -> None:
        """
        删除交易费率配置

        Args:
            config_id: 配置 ID
        """
        self._delete(f"trading-cost-configs/{config_id}/")

    def calculate_trading_cost(
        self,
        config_id: int,
        action: str,
        amount: float,
        is_shanghai: bool = False,
    ) -> dict[str, Any]:
        """
        计算交易费用

        Args:
            config_id: 费率配置 ID
            action: 交易方向（buy/sell）
            amount: 成交金额（元）
            is_shanghai: 是否上海市场

        Returns:
            费用明细
        """
        data: dict[str, Any] = {
            "action": action,
            "amount": amount,
            "is_shanghai": is_shanghai,
        }
        return self._post(f"trading-cost-configs/{config_id}/calculate/", json=data)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
