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

    @server.tool()
    def list_position_rules(
        strategy_id: int | None = None,
        is_active: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取仓位管理规则列表。"""
        client = AgomSAAFClient()
        return client.strategy.list_position_rules(
            strategy_id=strategy_id,
            is_active=is_active,
            limit=limit,
        )

    @server.tool()
    def create_position_rule(
        strategy_id: int,
        name: str,
        buy_price_expr: str,
        sell_price_expr: str,
        stop_loss_expr: str,
        take_profit_expr: str,
        position_size_expr: str,
        buy_condition_expr: str = "",
        sell_condition_expr: str = "",
        description: str = "",
        price_precision: int = 2,
        variables_schema: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        """创建仓位管理规则。"""
        client = AgomSAAFClient()
        return client.strategy.create_position_rule(
            strategy_id=strategy_id,
            name=name,
            buy_price_expr=buy_price_expr,
            sell_price_expr=sell_price_expr,
            stop_loss_expr=stop_loss_expr,
            take_profit_expr=take_profit_expr,
            position_size_expr=position_size_expr,
            buy_condition_expr=buy_condition_expr,
            sell_condition_expr=sell_condition_expr,
            description=description,
            price_precision=price_precision,
            variables_schema=variables_schema,
            metadata=metadata,
            is_active=is_active,
        )

    @server.tool()
    def evaluate_position_rule(
        rule_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按规则ID计算买卖价、止盈止损和仓位建议。"""
        client = AgomSAAFClient()
        return client.strategy.evaluate_position_rule(rule_id=rule_id, context=context)

    @server.tool()
    def get_strategy_position_rule(strategy_id: int) -> dict[str, Any]:
        """获取策略绑定的仓位管理规则。"""
        client = AgomSAAFClient()
        return client.strategy.get_strategy_position_rule(strategy_id=strategy_id)

    @server.tool()
    def evaluate_strategy_position_management(
        strategy_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按策略计算买卖价、止盈止损和仓位建议。"""
        client = AgomSAAFClient()
        return client.strategy.evaluate_strategy_position_management(
            strategy_id=strategy_id,
            context=context,
        )

