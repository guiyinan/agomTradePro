"""
AgomSAAF MCP Tools - Strategy 策略工具

提供策略管理相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomsaaf import AgomSAAFClient


def register_strategy_tools(server: FastMCP) -> None:
    """注册 Strategy 相关的 MCP 工具"""

    @server.tool()
    def list_strategies(
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取策略列表

        Args:
            status: 策略状态过滤（active/inactive/archived）
            limit: 返回数量限制

        Returns:
            策略列表

        Example:
            >>> strategies = list_strategies(status="active")
        """
        client = AgomSAAFClient()
        return client.strategy.list_strategies(status=status, limit=limit)

    @server.tool()
    def get_strategy(strategy_id: int) -> dict[str, Any]:
        """
        获取策略详情

        Args:
            strategy_id: 策略 ID

        Returns:
            策略详情

        Example:
            >>> strategy = get_strategy(1)
        """
        client = AgomSAAFClient()
        return client.strategy.get_strategy(strategy_id)

    @server.tool()
    def create_strategy(
        name: str,
        strategy_type: str,
        description: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        创建策略

        Args:
            name: 策略名称
            strategy_type: 策略类型（momentum/mean_reversion 等）
            description: 策略描述
            params: 策略参数（JSON 格式）

        Returns:
            创建的策略信息

        Example:
            >>> strategy = create_strategy(
            ...     name="动量策略",
            ...     strategy_type="momentum",
            ...     description="基于价格动量的选股策略",
            ...     params={"lookback": 20, "top_n": 10}
            ... )
        """
        client = AgomSAAFClient()
        return client.strategy.create_strategy(name, strategy_type, description, params)

    @server.tool()
    def execute_strategy(
        strategy_id: int,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """
        执行策略

        Args:
            strategy_id: 策略 ID
            as_of_date: 执行日期（ISO 格式，None 表示最新）

        Returns:
            执行结果

        Example:
            >>> result = execute_strategy(1)
        """
        client = AgomSAAFClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.strategy.execute_strategy(strategy_id, parsed_date)

    @server.tool()
    def get_strategy_performance(
        strategy_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        获取策略绩效

        Args:
            strategy_id: 策略 ID
            start_date: 开始日期（ISO 格式）
            end_date: 结束日期（ISO 格式）

        Returns:
            策略绩效数据

        Example:
            >>> perf = get_strategy_performance(
            ...     strategy_id=1,
            ...     start_date="2023-01-01",
            ...     end_date="2024-12-31"
            ... )
        """
        client = AgomSAAFClient()
        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None
        return client.strategy.get_strategy_performance(strategy_id, parsed_start, parsed_end)

    @server.tool()
    def get_strategy_signals(
        strategy_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取策略产生的信号列表

        Args:
            strategy_id: 策略 ID
            status: 信号状态过滤（可选）
            limit: 返回数量限制

        Returns:
            信号列表

        Example:
            >>> signals = get_strategy_signals(1)
        """
        client = AgomSAAFClient()
        return client.strategy.get_strategy_signals(strategy_id, status=status, limit=limit)

    @server.tool()
    def get_strategy_positions(strategy_id: int) -> list[dict[str, Any]]:
        """
        获取策略当前持仓

        Args:
            strategy_id: 策略 ID

        Returns:
            持仓列表

        Example:
            >>> positions = get_strategy_positions(1)
        """
        client = AgomSAAFClient()
        return client.strategy.get_strategy_positions(strategy_id)

