from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Simulated Trading 模拟盘交易模块

提供模拟盘交易相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule


class SimulatedTradingModule(BaseModule):
    """
    模拟盘交易模块

    提供模拟账户管理、交易执行、绩效查询等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 SimulatedTrading 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/simulated-trading")

    def list_accounts(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取模拟账户列表

        Args:
            status: 账户状态过滤（active/inactive/closed）
            limit: 返回数量限制

        Returns:
            模拟账户列表

        Example:
            >>> client = AgomSAAFClient()
            >>> accounts = client.simulated_trading.list_accounts(status="active")
            >>> for account in accounts:
            ...     print(f"{account['name']}: {account['total_value']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status

        response = self._get("accounts/", params=params)
        results = response.get("results", response)
        return results

    def get_account(self, account_id: int) -> dict[str, Any]:
        """
        获取单个模拟账户详情

        Args:
            account_id: 账户 ID

        Returns:
            账户详情

        Raises:
            NotFoundError: 当账户不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> account = client.simulated_trading.get_account(1)
            >>> print(f"账户名称: {account['name']}")
            >>> print(f"总市值: {account['total_value']}")
        """
        return self._get(f"accounts/{account_id}/")

    def create_account(
        self,
        name: str,
        initial_capital: float,
        start_date: date,
    ) -> dict[str, Any]:
        """
        创建模拟账户

        Args:
            name: 账户名称
            initial_capital: 初始资金
            start_date: 起始日期

        Returns:
            创建的账户信息

        Raises:
            ValidationError: 当参数验证失败时

        Example:
            >>> from datetime import date
            >>> client = AgomSAAFClient()
            >>> account = client.simulated_trading.create_account(
            ...     name="测试账户",
            ...     initial_capital=1000000.0,
            ...     start_date=date(2024, 1, 1)
            ... )
            >>> print(f"账户已创建: {account['id']}")
        """
        data: dict[str, Any] = {
            "name": name,
            "initial_capital": initial_capital,
            "start_date": start_date.isoformat(),
        }

        return self._post("accounts/", json=data)

    def execute_trade(
        self,
        account_id: int,
        asset_code: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        执行交易

        Args:
            account_id: 账户 ID
            asset_code: 资产代码
            side: 交易方向（buy/sell）
            quantity: 数量
            price: 价格（None 表示使用市价）

        Returns:
            交易执行结果

        Raises:
            ValidationError: 当参数验证失败时
            NotFoundError: 当账户不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.simulated_trading.execute_trade(
            ...     account_id=1,
            ...     asset_code="000001.SH",
            ...     side="buy",
            ...     quantity=1000,
            ...     price=10.5
            ... )
            >>> print(f"交易已执行: {result['order_id']}")
        """
        data: dict[str, Any] = {
            "account_id": account_id,
            "asset_code": asset_code,
            "side": side,
            "quantity": quantity,
        }

        if price is not None:
            data["price"] = price

        return self._post("execute-trade/", json=data)

    def get_positions(
        self,
        account_id: int,
        asset_code: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        获取模拟账户持仓

        Args:
            account_id: 账户 ID
            asset_code: 资产代码过滤（可选）

        Returns:
            持仓列表

        Example:
            >>> client = AgomSAAFClient()
            >>> positions = client.simulated_trading.get_positions(account_id=1)
            >>> for pos in positions:
            ...     print(f"{pos['asset_code']}: {pos['quantity']}")
        """
        params: dict[str, Any] = {"account_id": account_id}
        if asset_code is not None:
            params["asset_code"] = asset_code

        response = self._get("positions/", params=params)
        results = response.get("results", response)
        return results

    def get_performance(
        self,
        account_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取模拟账户绩效

        Args:
            account_id: 账户 ID
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            绩效数据，包括收益率、最大回撤、夏普比率等

        Example:
            >>> client = AgomSAAFClient()
            >>> perf = client.simulated_trading.get_performance(account_id=1)
            >>> print(f"总收益: {perf['total_return']:.2%}")
            >>> print(f"年化收益: {perf['annual_return']:.2%}")
        """
        params: dict[str, Any] = {"account_id": account_id}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()

        return self._get("performance/", params=params)

    def get_trade_history(
        self,
        account_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取交易历史

        Args:
            account_id: 账户 ID
            limit: 返回数量限制

        Returns:
            交易历史列表

        Example:
            >>> client = AgomSAAFClient()
            >>> trades = client.simulated_trading.get_trade_history(account_id=1)
            >>> for trade in trades:
            ...     print(f"{trade['created_at']}: {trade['side']} {trade['asset_code']}")
        """
        params: dict[str, Any] = {"account_id": account_id, "limit": limit}
        response = self._get("trade-history/", params=params)
        results = response.get("results", response)
        return results

    def close_position(
        self,
        account_id: int,
        asset_code: str,
    ) -> dict[str, Any]:
        """
        平仓

        Args:
            account_id: 账户 ID
            asset_code: 资产代码

        Returns:
            平仓结果

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.simulated_trading.close_position(
            ...     account_id=1,
            ...     asset_code="000001.SH"
            ... )
            >>> print(f"已平仓: {result['order_id']}")
        """
        data: dict[str, Any] = {
            "account_id": account_id,
            "asset_code": asset_code,
        }

        return self._post("close-position/", json=data)

    def reset_account(
        self,
        account_id: int,
        new_initial_capital: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        重置模拟账户

        Args:
            account_id: 账户 ID
            new_initial_capital: 新的初始资金（None 表示使用原值）

        Returns:
            重置后的账户信息

        Example:
            >>> client = AgomSAAFClient()
            >>> account = client.simulated_trading.reset_account(account_id=1)
            >>> print(f"账户已重置")
        """
        data: dict[str, Any] = {}
        if new_initial_capital is not None:
            data["new_initial_capital"] = new_initial_capital

        return self._post(f"accounts/{account_id}/reset/", json=data)
