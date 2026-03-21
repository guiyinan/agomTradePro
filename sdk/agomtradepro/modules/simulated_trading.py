from typing import TYPE_CHECKING
"""
AgomTradePro SDK - Simulated Trading 模拟盘交易模块

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
            client: AgomTradePro 客户端实例
        """
        # Canonical simulated trading endpoints are served under /api/simulated-trading/*.
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
            >>> client = AgomTradeProClient()
            >>> accounts = client.simulated_trading.list_accounts(status="active")
            >>> for account in accounts:
            ...     print(f"{account['name']}: {account['total_value']}")
        """
        params: dict[str, Any] = {"active_only": True}
        if status is not None and status.lower() in {"inactive", "closed"}:
            params["active_only"] = False

        response = self._get("accounts/", params=params)
        if isinstance(response, dict):
            return response.get("accounts", [])
        return response

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
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.get_account(1)
            >>> print(f"账户名称: {account['name']}")
            >>> print(f"总市值: {account['total_value']}")
        """
        response = self._get(f"accounts/{account_id}/")
        if isinstance(response, dict):
            return response.get("account", response)
        return response

    def delete_account(self, account_id: int) -> dict[str, Any]:
        """
        删除单个模拟账户。

        Args:
            account_id: 账户 ID

        Returns:
            删除结果
        """
        return self._delete(f"accounts/{account_id}/")

    def batch_delete_accounts(self, account_ids: list[int]) -> dict[str, Any]:
        """
        批量删除模拟账户。

        Args:
            account_ids: 账户 ID 列表

        Returns:
            批量删除结果
        """
        return self._post("accounts/batch-delete/", json={"account_ids": account_ids})

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
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.create_account(
            ...     name="测试账户",
            ...     initial_capital=1000000.0,
            ...     start_date=date(2024, 1, 1)
            ... )
            >>> print(f"账户已创建: {account['id']}")
        """
        data: dict[str, Any] = {
            "account_name": name,
            "initial_capital": initial_capital,
            "max_position_pct": 20.0,
            "stop_loss_pct": 10.0,
            "commission_rate": 0.0003,
            "slippage_rate": 0.001,
        }

        response = self._post("accounts/", json=data)
        if isinstance(response, dict):
            return response.get("account", response)
        return response

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
            >>> client = AgomTradeProClient()
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
            "asset_code": asset_code,
            "asset_name": asset_code,
            "asset_type": "fund",
            "action": side.lower(),
            "quantity": quantity,
            "reason": "MCP simulated ETF allocation",
        }

        if price is not None:
            data["price"] = price

        return self._post(f"accounts/{account_id}/trade/", json=data)

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
            >>> client = AgomTradeProClient()
            >>> positions = client.simulated_trading.get_positions(account_id=1)
            >>> for pos in positions:
            ...     print(f"{pos['asset_code']}: {pos['quantity']}")
        """
        response = self._get(f"accounts/{account_id}/positions/")
        if isinstance(response, dict):
            positions = response.get("positions", [])
            if asset_code is not None:
                positions = [p for p in positions if p.get("asset_code") == asset_code]
            return positions
        return response

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
            >>> client = AgomTradeProClient()
            >>> perf = client.simulated_trading.get_performance(account_id=1)
            >>> print(f"总收益: {perf['total_return']:.2%}")
            >>> print(f"年化收益: {perf['annual_return']:.2%}")
        """
        response = self._get(f"accounts/{account_id}/performance/")
        if isinstance(response, dict):
            return response.get("performance", response)
        return response

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
            >>> client = AgomTradeProClient()
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
            >>> client = AgomTradeProClient()
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
            >>> client = AgomTradeProClient()
            >>> account = client.simulated_trading.reset_account(account_id=1)
            >>> print(f"账户已重置")
        """
        data: dict[str, Any] = {}
        if new_initial_capital is not None:
            data["new_initial_capital"] = new_initial_capital

        return self._post(f"accounts/{account_id}/reset/", json=data)

    def run_daily_inspection(
        self,
        account_id: int,
        strategy_id: Optional[int] = None,
        inspection_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        手动执行账户日更巡检并落库。
        """
        data: dict[str, Any] = {}
        if strategy_id is not None:
            data["strategy_id"] = strategy_id
        if inspection_date is not None:
            data["inspection_date"] = inspection_date.isoformat()
        return self._post(f"accounts/{account_id}/inspections/run/", json=data)

    def list_daily_inspections(
        self,
        account_id: int,
        limit: int = 20,
        inspection_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        查询账户日更巡检历史报告。
        """
        params: dict[str, Any] = {"limit": limit}
        if inspection_date is not None:
            params["inspection_date"] = inspection_date.isoformat()
        return self._get(f"accounts/{account_id}/inspections/", params=params)
