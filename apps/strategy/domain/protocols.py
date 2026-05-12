"""
Domain 层 Protocol 接口定义

遵循项目架构约束：
- 使用 typing.Protocol 定义接口
- 通过依赖注入实现松耦合
- 不依赖具体实现
"""
from abc import abstractmethod
from typing import Any, Optional, Protocol

from .entities import (
    AIConfig,
    RuleCondition,
    SignalRecommendation,
    Strategy,
    StrategyExecutionResult,
)

# ========================================================================
# Repository Protocol
# ========================================================================

class StrategyRepositoryProtocol(Protocol):
    """策略仓储接口"""

    def save(self, strategy: Strategy) -> int:
        """
        保存策略，返回策略ID

        Args:
            strategy: 策略实体

        Returns:
            策略ID
        """
        ...

    def get_by_id(self, strategy_id: int) -> Strategy | None:
        """
        根据ID获取策略

        Args:
            strategy_id: 策略ID

        Returns:
            策略实体，如果不存在返回 None
        """
        ...

    def get_by_user(
        self,
        user_id: int,
        is_active: bool = True
    ) -> list[Strategy]:
        """
        获取用户的策略列表

        Args:
            user_id: 用户ID
            is_active: 是否只获取激活的策略

        Returns:
            策略实体列表
        """
        ...

    def get_active_strategies_for_portfolio(
        self,
        portfolio_id: int
    ) -> list[Strategy]:
        """
        获取投资组合的激活策略

        Args:
            portfolio_id: 投资组合ID

        Returns:
            策略实体列表
        """
        ...

    def delete(self, strategy_id: int) -> bool:
        """
        删除策略

        Args:
            strategy_id: 策略ID

        Returns:
            是否删除成功
        """
        ...


class RuleConditionRepositoryProtocol(Protocol):
    """规则条件仓储接口"""

    def save(self, condition: RuleCondition) -> int:
        """
        保存规则条件

        Args:
            condition: 规则条件实体

        Returns:
            规则条件ID
        """
        ...

    def get_by_strategy(self, strategy_id: int) -> list[RuleCondition]:
        """
        获取策略的所有规则条件

        Args:
            strategy_id: 策略ID

        Returns:
            规则条件实体列表
        """
        ...

    def delete_by_strategy(self, strategy_id: int) -> bool:
        """
        删除策略的所有规则条件

        Args:
            strategy_id: 策略ID

        Returns:
            是否删除成功
        """
        ...


class StrategyExecutionLogRepositoryProtocol(Protocol):
    """策略执行日志仓储接口"""

    def save(self, result: StrategyExecutionResult) -> int:
        """
        保存执行日志

        Args:
            result: 策略执行结果

        Returns:
            日志ID
        """
        ...

    def get_by_strategy(
        self,
        strategy_id: int,
        limit: int = 100
    ) -> list[StrategyExecutionResult]:
        """
        获取策略的执行日志

        Args:
            strategy_id: 策略ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        ...

    def get_by_portfolio(
        self,
        portfolio_id: int,
        limit: int = 100
    ) -> list[StrategyExecutionResult]:
        """
        获取投资组合的执行日志

        Args:
            portfolio_id: 投资组合ID
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        ...


# ========================================================================
# Service Protocol
# ========================================================================

class RuleEvaluatorProtocol(Protocol):
    """规则评估器接口"""

    def evaluate(
        self,
        condition: RuleCondition,
        context: dict[str, Any]
    ) -> bool:
        """
        评估规则条件

        Args:
            condition: 规则条件
            context: 上下文数据（宏观数据、Regime等）

        Returns:
            是否满足条件
        """
        ...


class ScriptExecutorProtocol(Protocol):
    """脚本执行器接口"""

    def execute(
        self,
        script_code: str,
        context: dict[str, Any],
        allowed_modules: list[str]
    ) -> list[SignalRecommendation]:
        """
        执行策略脚本

        Args:
            script_code: 脚本代码
            context: 上下文数据
            allowed_modules: 允许的模块列表

        Returns:
            信号推荐列表
        """
        ...


class AIStrategyExecutorProtocol(Protocol):
    """AI策略执行器接口"""

    def execute(
        self,
        strategy_id: int,
        context: dict[str, Any],
        ai_config: AIConfig
    ) -> list[SignalRecommendation]:
        """
        执行AI策略

        Args:
            strategy_id: 策略ID
            context: 上下文数据
            ai_config: AI配置

        Returns:
            信号推荐列表
        """
        ...


# ========================================================================
# External Service Protocol（集成现有系统）
# ========================================================================

class MacroDataProviderProtocol(Protocol):
    """宏观数据提供者接口"""

    def get_indicator(self, indicator_code: str) -> float | None:
        """
        获取宏观指标值

        Args:
            indicator_code: 指标代码（如 CN_PMI_MANUFACTURING）

        Returns:
            指标值，如果不存在返回 None
        """
        ...

    def get_all_indicators(self) -> dict[str, float]:
        """
        获取所有宏观指标

        Returns:
            指标代码到值的映射
        """
        ...


class RegimeProviderProtocol(Protocol):
    """Regime 提供者接口"""

    def get_current_regime(self) -> dict[str, Any]:
        """
        获取当前Regime状态

        Returns:
            Regime 状态字典，包含：
            - dominant_regime: 主导 Regime (HG/HD/LG/LD)
            - confidence: 置信度
            - growth_momentum_z: 增长动量 Z-score
            - inflation_momentum_z: 通胀动量 Z-score
        """
        ...


class AssetPoolProviderProtocol(Protocol):
    """资产池提供者接口"""

    def get_investable_assets(
        self,
        min_score: float = 60.0,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        获取可投资产列表

        Args:
            min_score: 最低评分
            limit: 返回数量限制

        Returns:
            资产列表，每个资产包含：
            - asset_code: 资产代码
            - asset_name: 资产名称
            - total_score: 总评分
            - regime_score: Regime 评分
            - policy_score: 政策评分
        """
        ...


class SignalProviderProtocol(Protocol):
    """信号提供者接口"""

    def get_valid_signals(self) -> list[dict[str, Any]]:
        """
        获取有效信号列表

        Returns:
            信号列表，每个信号包含：
            - signal_id: 信号ID
            - asset_code: 资产代码
            - direction: 方向 (LONG/SHORT)
            - logic_desc: 逻辑描述
            - target_regime: 目标 Regime
        """
        ...


class PortfolioDataProviderProtocol(Protocol):
    """投资组合数据提供者接口"""

    def get_positions(self, portfolio_id: int) -> list[dict[str, Any]]:
        """
        获取投资组合持仓

        Args:
            portfolio_id: 投资组合ID

        Returns:
            持仓列表，每个持仓包含：
            - asset_code: 资产代码
            - asset_name: 资产名称
            - quantity: 持仓数量
            - avg_cost: 平均成本
            - market_value: 市值
        """
        ...

    def get_cash(self, portfolio_id: int) -> float:
        """
        获取投资组合现金

        Args:
            portfolio_id: 投资组合ID

        Returns:
            现金余额
        """
        ...


class AssetNameResolverProtocol(Protocol):
    """资产名称解析接口"""

    def resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        """
        批量解析资产名称。

        Args:
            codes: 资产代码列表

        Returns:
            资产代码到名称的映射
        """
        ...


class AssetClassValueProtocol(Protocol):
    """Minimal asset-class value interface for allocation services."""

    value: str


class PositionLikeProtocol(Protocol):
    """Minimal position interface required by allocation advice generation."""

    asset_code: str
    market_value: Any
    asset_class: AssetClassValueProtocol


# ========================================================================
# M3: 执行适配器协议
# ========================================================================

class ExecutionAdapterProtocol(Protocol):
    """
    执行适配器接口

    统一的订单执行接口，支持：
    - PaperAdapter: 模拟执行
    - BrokerAdapter: 实盘执行
    """

    @abstractmethod
    def submit_order(self, intent: 'OrderIntent') -> str:
        """
        提交订单

        Args:
            intent: 订单意图

        Returns:
            broker_order_id: 券商订单ID

        Raises:
            ExecutionError: 执行失败
        """
        ...

    @abstractmethod
    def query_order_status(self, broker_order_id: str) -> dict[str, Any]:
        """
        查询订单状态

        Args:
            broker_order_id: 券商订单ID

        Returns:
            订单状态信息，包含：
            - status: 订单状态
            - filled_qty: 已成交数量
            - filled_price: 成交均价
            - remaining_qty: 剩余数量
            - error_message: 错误信息（如果有）
        """
        ...

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """
        撤销订单

        Args:
            broker_order_id: 券商订单ID

        Returns:
            是否撤销成功
        """
        ...

    @abstractmethod
    def get_name(self) -> str:
        """
        获取适配器名称

        Returns:
            适配器名称（如 "paper", "broker_xxx"）
        """
        ...

    @abstractmethod
    def is_live(self) -> bool:
        """
        是否是实盘模式

        Returns:
            True 表示实盘， False 表示模拟
        """
        ...


class OrderIntentRepositoryProtocol(Protocol):
    """订单意图仓储接口"""

    @abstractmethod
    def save(self, intent: 'OrderIntent') -> 'OrderIntent':
        """
        保存订单意图

        Args:
            intent: 订单意图

        Returns:
            保存后的订单意图
        """
        ...

    @abstractmethod
    def get_by_id(self, intent_id: str) -> Optional['OrderIntent']:
        """
        根据ID获取订单意图

        Args:
            intent_id: 订单意图ID

        Returns:
            订单意图，如果不存在返回 None
        """
        ...

    @abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str) -> Optional['OrderIntent']:
        """
        根据幂等键获取订单意图

        Args:
            idempotency_key: 幂等键

        Returns:
            订单意图，如果不存在返回 None
        """
        ...

    @abstractmethod
    def update_status(self, intent_id: str, status: 'OrderStatus') -> bool:
        """
        更新订单状态

        Args:
            intent_id: 订单意图ID
            status: 新状态

        Returns:
            是否更新成功
        """
        ...

    @abstractmethod
    def get_pending_intents(self, portfolio_id: int) -> list['OrderIntent']:
        """
        获取待处理的订单意图

        Args:
            portfolio_id: 投资组合ID

        Returns:
            待处理的订单意图列表
        """
        ...
