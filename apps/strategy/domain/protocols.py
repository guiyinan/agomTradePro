"""
Domain 层 Protocol 接口定义

遵循项目架构约束：
- 使用 typing.Protocol 定义接口
- 通过依赖注入实现松耦合
- 不依赖具体实现
"""
from typing import List, Optional, Protocol, Dict, Any
from abc import ABC, abstractmethod

from .entities import (
    Strategy,
    RuleCondition,
    StrategyExecutionResult,
    SignalRecommendation,
    RiskControlParams,
    AIConfig
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

    def get_by_id(self, strategy_id: int) -> Optional[Strategy]:
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
    ) -> List[Strategy]:
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
    ) -> List[Strategy]:
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

    def get_by_strategy(self, strategy_id: int) -> List[RuleCondition]:
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
    ) -> List[StrategyExecutionResult]:
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
    ) -> List[StrategyExecutionResult]:
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
        context: Dict[str, Any]
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
        context: Dict[str, Any],
        allowed_modules: List[str]
    ) -> List[SignalRecommendation]:
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
        context: Dict[str, Any],
        ai_config: AIConfig
    ) -> List[SignalRecommendation]:
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

    def get_indicator(self, indicator_code: str) -> Optional[float]:
        """
        获取宏观指标值

        Args:
            indicator_code: 指标代码（如 CN_PMI_MANUFACTURING）

        Returns:
            指标值，如果不存在返回 None
        """
        ...

    def get_all_indicators(self) -> Dict[str, float]:
        """
        获取所有宏观指标

        Returns:
            指标代码到值的映射
        """
        ...


class RegimeProviderProtocol(Protocol):
    """Regime 提供者接口"""

    def get_current_regime(self) -> Dict[str, Any]:
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
    ) -> List[Dict[str, Any]]:
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

    def get_valid_signals(self) -> List[Dict[str, Any]]:
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

    def get_positions(self, portfolio_id: int) -> List[Dict[str, Any]]:
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
