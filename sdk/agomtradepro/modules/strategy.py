"""
AgomTradePro SDK - Strategy 策略模块

提供策略管理相关的 API 操作。
"""

from datetime import date
from typing import Any

from .base import BaseModule


class StrategyModule(BaseModule):
    """
    策略模块

    提供策略查询、执行、绩效追踪等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Strategy 模块

        Args:
            client: AgomTradePro 客户端实例
        """
        # Canonical strategy endpoints are served under /api/strategy/*.
        super().__init__(client, "/api/strategy")

    def list_strategies(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取策略列表

        Args:
            status: 策略状态过滤（active/inactive/archived）
            limit: 返回数量限制

        Returns:
            策略列表

        Example:
            >>> client = AgomTradeProClient()
            >>> strategies = client.strategy.list_strategies(status="active")
            >>> for s in strategies:
            ...     print(f"{s['name']}: {s['type']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status

        response = self._get("strategies/", params=params)
        results = response.get("results", response)
        return results

    def get_strategy(self, strategy_id: int) -> dict[str, Any]:
        """
        获取策略详情

        Args:
            strategy_id: 策略 ID

        Returns:
            策略详情

        Raises:
            NotFoundError: 当策略不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> strategy = client.strategy.get_strategy(1)
            >>> print(f"策略名称: {strategy['name']}")
            >>> print(f"策略类型: {strategy['type']}")
        """
        return self._get(f"strategies/{strategy_id}/")

    def get_strategy_signals(
        self,
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
            >>> client = AgomTradeProClient()
            >>> signals = client.strategy.get_strategy_signals(1)
            >>> for signal in signals:
            ...     print(f"{signal['created_at']}: {signal['asset_code']}")
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status

        response = self._get(f"strategies/{strategy_id}/signals/", params=params)
        results = response.get("results", response)
        return results

    def execute_strategy(
        self,
        strategy_id: int,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        """
        执行策略

        运行策略并生成交易信号。

        Args:
            strategy_id: 策略 ID
            as_of_date: 执行日期（None 表示最新）

        Returns:
            执行结果，包括生成的信号数量

        Raises:
            ValidationError: 当策略参数无效时
            NotFoundError: 当策略不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> result = client.strategy.execute_strategy(1)
            >>> print(f"生成信号数: {result['signals_created']}")
        """
        data: dict[str, Any] = {}
        if as_of_date is not None:
            data["as_of_date"] = as_of_date.isoformat()

        return self._post(f"strategies/{strategy_id}/execute/", json=data)

    def bind_portfolio_strategy(
        self,
        portfolio_id: int,
        strategy_id: int,
    ) -> dict[str, Any]:
        """
        绑定策略到投资组合（激活分配关系）。

        Notes:
            后端语义为“一个账户只保留一个激活策略分配”，
            绑定新策略时会自动停用该账户其他激活分配。
        """
        return self._post(
            "bind-strategy/",
            json={"portfolio_id": portfolio_id, "strategy_id": strategy_id},
        )

    def unbind_portfolio_strategy(
        self,
        portfolio_id: int,
    ) -> dict[str, Any]:
        """
        解绑投资组合策略（停用该账户全部激活分配）。
        """
        return self._post(
            "unbind-strategy/",
            json={"portfolio_id": portfolio_id},
        )

    def get_strategy_performance(
        self,
        strategy_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """
        获取策略绩效

        Args:
            strategy_id: 策略 ID
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            策略绩效数据

        Example:
            >>> from datetime import date
            >>> client = AgomTradeProClient()
            >>> perf = client.strategy.get_strategy_performance(
            ...     strategy_id=1,
            ...     start_date=date(2023, 1, 1),
            ...     end_date=date(2024, 12, 31)
            ... )
            >>> print(f"总收益: {perf['total_return']:.2%}")
        """
        params: dict[str, Any] = {}

        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()

        return self._get(f"strategies/{strategy_id}/performance/", params=params)

    def create_strategy(
        self,
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
            params: 策略参数

        Returns:
            创建的策略信息

        Raises:
            ValidationError: 当参数验证失败时

        Example:
            >>> client = AgomTradeProClient()
            >>> strategy = client.strategy.create_strategy(
            ...     name="动量策略",
            ...     strategy_type="momentum",
            ...     description="基于价格动量的选股策略",
            ...     params={"lookback": 20, "top_n": 10}
            ... )
            >>> print(f"策略已创建: {strategy['id']}")
        """
        data: dict[str, Any] = {
            "name": name,
            "strategy_type": strategy_type,
            "description": description,
            "version": int(params.get("version", 1)),
            "is_active": bool(params.get("is_active", True)),
            "max_position_pct": float(params.get("max_position_pct", 20.0)),
            "max_total_position_pct": float(params.get("max_total_position_pct", 95.0)),
            "stop_loss_pct": params.get("stop_loss_pct"),
        }
        if params.get("created_by") is not None:
            data["created_by"] = int(params["created_by"])

        return self._post("strategies/", json=data)

    def update_strategy(
        self,
        strategy_id: int,
        name: str | None = None,
        description: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        更新策略

        Args:
            strategy_id: 策略 ID
            name: 新名称（可选）
            description: 新描述（可选）
            params: 新参数（可选）

        Returns:
            更新后的策略信息

        Example:
            >>> client = AgomTradeProClient()
            >>> strategy = client.strategy.update_strategy(
            ...     strategy_id=1,
            ...     name="更新后的策略名"
            ... )
        """
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description
        if params is not None:
            data["params"] = params

        return self._put(f"strategies/{strategy_id}/", json=data)

    def list_ai_strategy_configs(
        self,
        strategy_id: int | None = None,
        approval_mode: str | None = None,
        ai_provider_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取 AI 策略配置列表。"""
        params: dict[str, Any] = {"limit": limit}
        if strategy_id is not None:
            params["strategy"] = strategy_id
        if approval_mode is not None:
            params["approval_mode"] = approval_mode
        if ai_provider_id is not None:
            params["ai_provider"] = ai_provider_id
        response = self._get("ai-configs/", params=params)
        return response.get("results", response)

    def get_strategy_ai_config(self, strategy_id: int) -> dict[str, Any]:
        """获取指定策略的一条 AI 配置；不存在时返回空结果。"""
        configs = self.list_ai_strategy_configs(strategy_id=strategy_id, limit=1)
        if configs:
            return configs[0]
        return {"strategy": strategy_id, "exists": False}

    def create_ai_strategy_config(
        self,
        strategy_id: int,
        prompt_template_id: int | None = None,
        chain_config_id: int | None = None,
        ai_provider_id: int | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        approval_mode: str = "conditional",
        confidence_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """创建 AI 策略配置。"""
        data: dict[str, Any] = {
            "strategy": strategy_id,
            "prompt_template": prompt_template_id,
            "chain_config": chain_config_id,
            "ai_provider": ai_provider_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "approval_mode": approval_mode,
            "confidence_threshold": confidence_threshold,
        }
        return self._post("ai-configs/", json=data)

    def update_ai_strategy_config(
        self,
        config_id: int,
        **updates: Any,
    ) -> dict[str, Any]:
        """更新 AI 策略配置。"""
        return self._patch(f"ai-configs/{config_id}/", json=updates)

    def delete_strategy(self, strategy_id: int) -> None:
        """
        删除策略

        Args:
            strategy_id: 策略 ID

        Raises:
            NotFoundError: 当策略不存在时

        Example:
            >>> client = AgomTradeProClient()
            >>> client.strategy.delete_strategy(1)
            >>> print("策略已删除")
        """
        self._delete(f"strategies/{strategy_id}/")

    def get_strategy_positions(
        self,
        strategy_id: int,
    ) -> list[dict[str, Any]]:
        """
        获取策略当前持仓

        Args:
            strategy_id: 策略 ID

        Returns:
            持仓列表

        Example:
            >>> client = AgomTradeProClient()
            >>> positions = client.strategy.get_strategy_positions(1)
            >>> for pos in positions:
            ...     print(f"{pos['asset_code']}: {pos['quantity']}")
        """
        response = self._get(f"strategies/{strategy_id}/positions/")
        results = response.get("results", response)
        return results

    def get_strategy_trades(
        self,
        strategy_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取策略交易历史

        Args:
            strategy_id: 策略 ID
            limit: 返回数量限制

        Returns:
            交易历史列表

        Example:
            >>> client = AgomTradeProClient()
            >>> trades = client.strategy.get_strategy_trades(1)
            >>> for trade in trades:
            ...     print(f"{trade['date']}: {trade['side']} {trade['asset_code']}")
        """
        params: dict[str, Any] = {"limit": limit}
        response = self._get(f"strategies/{strategy_id}/trades/", params=params)
        results = response.get("results", response)
        return results

    def list_position_rules(
        self,
        strategy_id: int | None = None,
        is_active: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取仓位管理规则列表。"""
        params: dict[str, Any] = {"limit": limit}
        if strategy_id is not None:
            params["strategy"] = strategy_id
        if is_active is not None:
            params["is_active"] = is_active
        response = self._get("position-rules/", params=params)
        return response.get("results", response)

    def get_position_rule(self, rule_id: int) -> dict[str, Any]:
        """获取单条仓位管理规则。"""
        return self._get(f"position-rules/{rule_id}/")

    def create_position_rule(
        self,
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
        data: dict[str, Any] = {
            "strategy": strategy_id,
            "name": name,
            "description": description,
            "is_active": is_active,
            "price_precision": price_precision,
            "variables_schema": variables_schema or [],
            "buy_condition_expr": buy_condition_expr,
            "sell_condition_expr": sell_condition_expr,
            "buy_price_expr": buy_price_expr,
            "sell_price_expr": sell_price_expr,
            "stop_loss_expr": stop_loss_expr,
            "take_profit_expr": take_profit_expr,
            "position_size_expr": position_size_expr,
            "metadata": metadata or {},
        }
        return self._post("position-rules/", json=data)

    def update_position_rule(
        self,
        rule_id: int,
        **updates: Any,
    ) -> dict[str, Any]:
        """更新仓位管理规则。"""
        return self._patch(f"position-rules/{rule_id}/", json=updates)

    def evaluate_position_rule(
        self,
        rule_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按规则ID评估仓位管理建议。"""
        return self._post(f"position-rules/{rule_id}/evaluate/", json={"context": context})

    def get_strategy_position_rule(self, strategy_id: int) -> dict[str, Any]:
        """获取策略绑定的仓位管理规则。"""
        return self._get(f"strategies/{strategy_id}/position_rule/")

    def evaluate_strategy_position_management(
        self,
        strategy_id: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """按策略评估仓位管理建议。"""
        return self._post(
            f"strategies/{strategy_id}/evaluate_position_management/",
            json={"context": context},
        )
