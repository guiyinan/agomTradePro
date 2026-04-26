"""
Strategy Execution Gateway.

Application 层网关服务， 为 simulated_trading 模块提供策略执行的统一接口。

重构说明 (2026-03-11):
- 将策略执行逻辑从 simulated_trading 模块解耦
- 通过网关模式访问， 避免直接导入 StrategyExecutor
- 支持依赖注入便于测试

使用方式:
    # 在 simulated_trading 模块
    from apps.strategy.application.execution_gateway import StrategyExecutionGateway

    gateway = StrategyExecutionGateway()
    result = gateway.execute_for_account(
        strategy_id=1,
        account_id=1,
        as_of_date=date.today()
    )
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Protocol

from apps.strategy.application.repository_provider import (
    build_strategy_executor,
    get_strategy_gateway_repository,
)

logger = __import__('logging').getLogger(__name__)


# ============================================================================
# Data Transfer Objects
# ============================================================================

@dataclass(frozen=True)
class ExecutionRequest:
    """策略执行请求"""
    strategy_id: int
    account_id: int
    as_of_date: date


@dataclass(frozen=True)
class SignalInfo:
    """信号信息"""
    signal_id: int | None
    asset_code: str
    asset_name: str
    action: str  # buy / sell
    quantity: int | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class ExecutionResult:
    """策略执行结果"""
    success: bool
    signals: list[SignalInfo]
    error_message: str | None = None
    execution_time: float | None = None


@dataclass(frozen=True)
class InspectionSelection:
    """巡检所需的策略与仓位规则摘要。"""
    strategy_id: int | None
    position_rule_id: int | None
    rule_metadata: dict[str, Any]
    strategy_name: str | None = None
    strategy_type: str | None = None


# ============================================================================
# Gateway Protocol
# ============================================================================

class StrategyExecutorProtocol(Protocol):
    """策略执行器协议"""

    def execute_strategy(
        self,
        strategy_id: int,
        account_id: int,
        as_of_date: date | None = None
    ) -> dict[str, Any]:
        """
        执行策略

        Args:
            strategy_id: 策略 ID
            account_id: 账户 ID
            as_of_date: 分析时点

        Returns:
            执行结果字典
        """
        ...


class StrategyGatewayQueryProtocol(Protocol):
    """策略只读查询协议。"""

    def get_strategy_info(self, strategy_id: int) -> dict[str, Any] | None:
        ...

    def get_active_strategy_binding(self, account_id: int) -> dict[str, Any] | None:
        ...

    def get_inspection_selection(
        self,
        account_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        ...

    def evaluate_position_rule(
        self,
        rule_id: int | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...


# ============================================================================
# Gateway Implementation
# ============================================================================

class StrategyExecutionGateway:
    """
    策略执行网关

    为外部模块提供策略执行的统一接口。
    通过依赖注入方式解耦， 避免 simulated_trading 直接导入 StrategyExecutor。

    Example:
        >>> gateway = StrategyExecutionGateway()
        >>> result = gateway.execute_for_account(
        ...     strategy_id=1,
        ...     account_id=1,
        ...     as_of_date=date.today()
        ... )
        >>> if result.success:
        ...     for signal in result.signals:
        ...         print(f"{signal.action}: {signal.asset_code}")
    """

    def __init__(
        self,
        executor: StrategyExecutorProtocol | None = None,
        query_repository: StrategyGatewayQueryProtocol | None = None,
    ):
        """
        初始化网关

        Args:
            executor: 策略执行器 (可选， 支持依赖注入)
        """
        self._executor = executor
        self._query_repository = query_repository

    def _get_executor(self) -> StrategyExecutorProtocol:
        """
        获取策略执行器

        延迟导入 StrategyExecutor， 避免模块加载时的循环依赖。

        Returns:
            StrategyExecutor 实例
        """
        if self._executor is None:
            self._executor = build_strategy_executor()
        return self._executor

    def _get_query_repository(self) -> StrategyGatewayQueryProtocol:
        if self._query_repository is None:
            self._query_repository = get_strategy_gateway_repository()
        return self._query_repository

    def execute_for_account(
        self,
        strategy_id: int,
        account_id: int,
        as_of_date: date | None = None
    ) -> ExecutionResult:
        """
        为账户执行策略

        Args:
            strategy_id: 策略 ID
            account_id: 账户 ID
            as_of_date: 分析时点

        Returns:
            ExecutionResult
        """
        try:
            executor = self._get_executor()

            # 执行策略 — StrategyExecutor 使用 portfolio_id（与 account_id 对应）
            raw_result = executor.execute_strategy(
                strategy_id=strategy_id,
                portfolio_id=account_id,
            )

            if not raw_result.is_success:
                return ExecutionResult(
                    success=False,
                    signals=[],
                    error_message=raw_result.error_message or '策略执行失败'
                )

            # 转换信号（StrategyExecutionResult.signals -> [SignalRecommendation]）
            signals = []
            for sig in raw_result.signals:
                signals.append(SignalInfo(
                    signal_id=None,
                    asset_code=sig.asset_code,
                    asset_name=sig.asset_name,
                    action=sig.action.value if hasattr(sig.action, 'value') else str(sig.action),
                    quantity=sig.quantity,
                    confidence=sig.confidence,
                    reason=sig.reason,
                ))

            return ExecutionResult(
                success=True,
                signals=signals,
                execution_time=raw_result.execution_time,
            )

        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            return ExecutionResult(
                success=False,
                signals=[],
                error_message=str(e)
            )

    def get_strategy_info(self, strategy_id: int) -> dict[str, Any] | None:
        """
        获取策略信息

        Args:
            strategy_id: 策略 ID

        Returns:
            策略信息字典或 None
        """
        try:
            return self._get_query_repository().get_strategy_info(strategy_id)
        except Exception as e:
            logger.error(f"Error getting strategy info: {e}")
            return None

    def get_active_strategy_binding(self, account_id: int) -> dict[str, Any] | None:
        """
        获取账户当前激活的策略绑定信息。

        Args:
            account_id: 账户 ID

        Returns:
            绑定信息字典或 None
        """
        try:
            return self._get_query_repository().get_active_strategy_binding(account_id)
        except Exception as e:
            logger.error(f"Error getting active strategy binding for account {account_id}: {e}")
            return None

    def is_strategy_active(self, strategy_id: int) -> bool:
        """
        检查策略是否活跃

        Args:
            strategy_id: 策略 ID

        Returns:
            是否活跃
        """
        info = self.get_strategy_info(strategy_id)
        return info is not None and info.get('is_active', False)

    def get_inspection_selection(
        self,
        account_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """获取日更巡检需要的策略和规则信息。"""
        try:
            return self._get_query_repository().get_inspection_selection(
                account_id=account_id,
                strategy_id=strategy_id,
            )
        except Exception as e:
            logger.error(f"Error getting inspection selection: {e}")
            return InspectionSelection(
                strategy_id=None,
                position_rule_id=None,
                rule_metadata={},
            )

    def evaluate_position_rule(
        self,
        rule_id: int | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """评估仓位管理规则并返回字典结果。"""
        if not rule_id:
            return None

        try:
            return self._get_query_repository().evaluate_position_rule(rule_id, context)
        except Exception as e:
            logger.error(f"Error evaluating position rule: {e}")
            return None


# ============================================================================
# 全局单例
# ============================================================================

_gateway_instance: StrategyExecutionGateway | None = None


def get_strategy_execution_gateway() -> StrategyExecutionGateway:
    """
    获取策略执行网关单例

    Returns:
        StrategyExecutionGateway 实例
    """
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = StrategyExecutionGateway()
    return _gateway_instance
