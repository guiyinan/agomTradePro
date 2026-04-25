"""
AgomTradePro MCP Tools - Strategy 策略工具

提供策略管理相关的 MCP 工具。
"""

from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


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
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
        try:
            return client.strategy.create_strategy(name, strategy_type, description, params)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": {
                    "name": name,
                    "strategy_type": strategy_type,
                    "description": description,
                    "params": params,
                },
            }

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
        client = AgomTradeProClient()
        parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
        return client.strategy.execute_strategy(strategy_id, parsed_date)

    @server.tool()
    def bind_portfolio_strategy(
        portfolio_id: int,
        strategy_id: int,
    ) -> dict[str, Any]:
        """
        绑定策略到投资组合。

        Notes:
            同一账户只保留一个激活策略分配，绑定新策略会自动停用旧分配。
        """
        client = AgomTradeProClient()
        return client.strategy.bind_portfolio_strategy(
            portfolio_id=portfolio_id,
            strategy_id=strategy_id,
        )

    @server.tool()
    def unbind_portfolio_strategy(
        portfolio_id: int,
    ) -> dict[str, Any]:
        """
        解绑投资组合策略（停用该账户所有激活分配）。
        """
        client = AgomTradeProClient()
        return client.strategy.unbind_portfolio_strategy(portfolio_id=portfolio_id)

    @server.tool()
    def list_ai_strategy_configs(
        strategy_id: int | None = None,
        approval_mode: str | None = None,
        ai_provider_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取 AI 策略配置列表。"""
        client = AgomTradeProClient()
        return client.strategy.list_ai_strategy_configs(
            strategy_id=strategy_id,
            approval_mode=approval_mode,
            ai_provider_id=ai_provider_id,
            limit=limit,
        )

    @server.tool()
    def get_strategy_ai_config(strategy_id: int) -> dict[str, Any]:
        """获取指定策略的 AI 执行参数配置。"""
        client = AgomTradeProClient()
        return client.strategy.get_strategy_ai_config(strategy_id=strategy_id)

    @server.tool()
    def create_ai_strategy_config(
        strategy_id: int,
        prompt_template_id: int | None = None,
        chain_config_id: int | None = None,
        ai_provider_id: int | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        approval_mode: str = "conditional",
        confidence_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """
        创建 AI 策略配置。

        approval_mode 支持 always、conditional、auto。
        """
        client = AgomTradeProClient()
        payload = {
            "strategy_id": strategy_id,
            "prompt_template_id": prompt_template_id,
            "chain_config_id": chain_config_id,
            "ai_provider_id": ai_provider_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "approval_mode": approval_mode,
            "confidence_threshold": confidence_threshold,
        }
        try:
            return client.strategy.create_ai_strategy_config(**payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def update_ai_strategy_config(
        config_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """更新 AI 策略配置。updates 使用 API 字段名。"""
        client = AgomTradeProClient()
        return client.strategy.update_ai_strategy_config(config_id=config_id, **updates)

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
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
        return client.strategy.get_strategy_positions(strategy_id)

    @server.tool()
    def list_position_rules(
        strategy_id: int | None = None,
        is_active: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取仓位管理规则列表。"""
        client = AgomTradeProClient()
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
        client = AgomTradeProClient()
        payload = {
            "strategy_id": strategy_id,
            "name": name,
            "buy_price_expr": buy_price_expr,
            "sell_price_expr": sell_price_expr,
            "stop_loss_expr": stop_loss_expr,
            "take_profit_expr": take_profit_expr,
            "position_size_expr": position_size_expr,
            "buy_condition_expr": buy_condition_expr,
            "sell_condition_expr": sell_condition_expr,
            "description": description,
            "price_precision": price_precision,
            "variables_schema": variables_schema,
            "metadata": metadata,
            "is_active": is_active,
        }
        try:
            return client.strategy.create_position_rule(**payload)
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "payload": payload,
            }

    @server.tool()
    def update_position_rule(
        rule_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """更新仓位管理规则。updates 使用 API 字段名。"""
        client = AgomTradeProClient()
        return client.strategy.update_position_rule(rule_id=rule_id, **updates)

    @server.tool()
    def evaluate_position_rule(
        rule_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按规则ID计算买卖价、止盈止损和仓位建议。"""
        client = AgomTradeProClient()
        return client.strategy.evaluate_position_rule(rule_id=rule_id, context=context)

    @server.tool()
    def get_strategy_position_rule(strategy_id: int) -> dict[str, Any]:
        """获取策略绑定的仓位管理规则。"""
        client = AgomTradeProClient()
        return client.strategy.get_strategy_position_rule(strategy_id=strategy_id)

    @server.tool()
    def evaluate_strategy_position_management(
        strategy_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按策略计算买卖价、止盈止损和仓位建议。"""
        client = AgomTradeProClient()
        return client.strategy.evaluate_strategy_position_management(
            strategy_id=strategy_id,
            context=context,
        )

