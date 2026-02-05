"""
AgomSAAF MCP Tools - Simulated Trading 模拟盘交易工具

提供模拟盘交易相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server import Server

from agomsaaf import AgomSAAFClient


def register_simulated_trading_tools(server: Server) -> None:
    """注册 SimulatedTrading 相关的 MCP 工具"""

    @server.tool()
    def list_simulated_accounts(
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取模拟账户列表

        Args:
            status: 账户状态过滤（active/inactive/closed）
            limit: 返回数量限制

        Returns:
            模拟账户列表

        Example:
            >>> accounts = list_simulated_accounts(status="active")
        """
        client = AgomSAAFClient()
        return client.simulated_trading.list_accounts(status=status, limit=limit)

    @server.tool()
    def get_simulated_account(account_id: int) -> dict[str, Any]:
        """
        获取模拟账户详情

        Args:
            account_id: 账户 ID

        Returns:
            账户详情

        Example:
            >>> account = get_simulated_account(1)
        """
        client = AgomSAAFClient()
        return client.simulated_trading.get_account(account_id)

    @server.tool()
    def create_simulated_account(
        name: str,
        initial_capital: float,
        start_date: str,
    ) -> dict[str, Any]:
        """
        创建模拟账户

        Args:
            name: 账户名称
            initial_capital: 初始资金
            start_date: 起始日期（ISO 格式，如 2024-01-01）

        Returns:
            创建的账户信息

        Example:
            >>> account = create_simulated_account(
            ...     name="测试账户",
            ...     initial_capital=1000000.0,
            ...     start_date="2024-01-01"
            ... )
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(start_date)
        return client.simulated_trading.create_account(name, initial_capital, parsed_date)

    @server.tool()
    def execute_simulated_trade(
        account_id: int,
        asset_code: str,
        side: str,
        quantity: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        """
        执行模拟交易

        Args:
            account_id: 账户 ID
            asset_code: 资产代码
            side: 交易方向（buy/sell）
            quantity: 数量
            price: 价格（None 表示市价）

        Returns:
            交易执行结果

        Example:
            >>> result = execute_simulated_trade(
            ...     account_id=1,
            ...     asset_code="000001.SH",
            ...     side="buy",
            ...     quantity=1000,
            ...     price=10.5
            ... )
        """
        client = AgomSAAFClient()
        return client.simulated_trading.execute_trade(account_id, asset_code, side, quantity, price)

    @server.tool()
    def get_simulated_positions(account_id: int) -> list[dict[str, Any]]:
        """
        获取模拟账户持仓

        Args:
            account_id: 账户 ID

        Returns:
            持仓列表

        Example:
            >>> positions = get_simulated_positions(account_id=1)
        """
        client = AgomSAAFClient()
        return client.simulated_trading.get_positions(account_id)

    @server.tool()
    def get_simulated_performance(account_id: int) -> dict[str, Any]:
        """
        获取模拟账户绩效

        Args:
            account_id: 账户 ID

        Returns:
            绩效数据

        Example:
            >>> perf = get_simulated_performance(account_id=1)
            >>> print(f"总收益: {perf['total_return']:.2%}")
        """
        client = AgomSAAFClient()
        return client.simulated_trading.get_performance(account_id)

    @server.tool()
    def reset_simulated_account(
        account_id: int,
        new_initial_capital: float | None = None,
    ) -> dict[str, Any]:
        """
        重置模拟账户

        Args:
            account_id: 账户 ID
            new_initial_capital: 新的初始资金（可选）

        Returns:
            重置后的账户信息

        Example:
            >>> account = reset_simulated_account(account_id=1)
        """
        client = AgomSAAFClient()
        return client.simulated_trading.reset_account(account_id, new_initial_capital)

    @server.tool()
    def close_simulated_position(
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
            >>> result = close_simulated_position(
            ...     account_id=1,
            ...     asset_code="000001.SH"
            ... )
        """
        client = AgomSAAFClient()
        return client.simulated_trading.close_position(account_id, asset_code)
