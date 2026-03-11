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
from typing import List, Optional, Dict, Any, Protocol
from decimal import Decimal

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
    signal_id: Optional[int]
    asset_code: str
    asset_name: str
    action: str  # buy / sell
    quantity: Optional[int]
    confidence: float
    reason: str


@dataclass(frozen=True)
class ExecutionResult:
    """策略执行结果"""
    success: bool
    signals: List[SignalInfo]
    error_message: Optional[str] = None
    execution_time: Optional[float] = None


@dataclass(frozen=True)
class InspectionSelection:
    """巡检所需的策略与仓位规则摘要。"""
    strategy_id: Optional[int]
    position_rule_id: Optional[int]
    rule_metadata: Dict[str, Any]
    strategy_name: Optional[str] = None
    strategy_type: Optional[str] = None


# ============================================================================
# Gateway Protocol
# ============================================================================

class StrategyExecutorProtocol(Protocol):
    """策略执行器协议"""

    def execute_strategy(
        self,
        strategy_id: int,
        account_id: int,
        as_of_date: Optional[date] = None
    ) -> Dict[str, Any]:
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
        executor: Optional[StrategyExecutorProtocol] = None
    ):
        """
        初始化网关

        Args:
            executor: 策略执行器 (可选， 支持依赖注入)
        """
        self._executor = executor

    def _get_executor(self) -> StrategyExecutorProtocol:
        """
        获取策略执行器

        延迟导入 StrategyExecutor， 避免模块加载时的循环依赖。

        Returns:
            StrategyExecutor 实例
        """
        if self._executor is None:
            # 延迟导入避免循环依赖
            from apps.strategy.application.strategy_executor import StrategyExecutor
            self._executor = StrategyExecutor()
        return self._executor

    def execute_for_account(
        self,
        strategy_id: int,
        account_id: int,
        as_of_date: Optional[date] = None
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

            # 执行策略
            raw_result = executor.execute_strategy(
                strategy_id=strategy_id,
                account_id=account_id,
                as_of_date=as_of_date
            )

            if not raw_result.get('is_success', False):
                return ExecutionResult(
                    success=False,
                    signals=[],
                    error_message=raw_result.get('error_message', '策略执行失败')
                )

            # 转换信号
            signals = []
            for sig in raw_result.get('signals', []):
                signals.append(SignalInfo(
                    signal_id=sig.get('signal_id'),
                    asset_code=sig.get('asset_code', ''),
                    asset_name=sig.get('asset_name', ''),
                    action=sig.get('action', ''),
                    quantity=sig.get('quantity'),
                    confidence=sig.get('confidence', 0.0),
                    reason=sig.get('reason', '')
                ))

            return ExecutionResult(
                success=True,
                signals=signals,
                execution_time=raw_result.get('execution_time')
            )

        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            return ExecutionResult(
                success=False,
                signals=[],
                error_message=str(e)
            )

    def get_strategy_info(self, strategy_id: int) -> Optional[Dict[str, Any]]:
        """
        获取策略信息

        Args:
            strategy_id: 策略 ID

        Returns:
            策略信息字典或 None
        """
        try:
            # 延迟导入避免循环依赖
            from apps.strategy.infrastructure.models import StrategyModel

            strategy = StrategyModel._default_manager.filter(
                id=strategy_id
            ).first()

            if strategy:
                return {
                    'strategy_id': strategy.id,
                    'name': strategy.name,
                    'strategy_type': strategy.strategy_type,
                    'is_active': strategy.is_active,
                    'description': strategy.description
                }
            return None

        except Exception as e:
            logger.error(f"Error getting strategy info: {e}")
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
        strategy_id: Optional[int] = None,
    ) -> InspectionSelection:
        """获取日更巡检需要的策略和规则信息。"""
        try:
            from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel

            if strategy_id:
                strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
                rule = (
                    PositionManagementRuleModel._default_manager.filter(
                        strategy_id=strategy_id,
                        is_active=True,
                    )
                    .order_by("-updated_at")
                    .first()
                )
                return InspectionSelection(
                    strategy_id=getattr(strategy, "id", None),
                    position_rule_id=getattr(rule, "id", None),
                    rule_metadata=getattr(rule, "metadata", {}) or {},
                    strategy_name=getattr(strategy, "name", None),
                    strategy_type=getattr(strategy, "strategy_type", None),
                )

            rule = (
                PositionManagementRuleModel._default_manager.filter(
                    is_active=True,
                    metadata__account_id=account_id,
                )
                .select_related("strategy")
                .order_by("-updated_at")
                .first()
            )
            strategy = getattr(rule, "strategy", None)
            return InspectionSelection(
                strategy_id=getattr(strategy, "id", None),
                position_rule_id=getattr(rule, "id", None),
                rule_metadata=getattr(rule, "metadata", {}) or {},
                strategy_name=getattr(strategy, "name", None),
                strategy_type=getattr(strategy, "strategy_type", None),
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
        rule_id: Optional[int],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """评估仓位管理规则并返回字典结果。"""
        if not rule_id:
            return None

        try:
            from apps.strategy.infrastructure.models import PositionManagementRuleModel
            from apps.strategy.application.position_management_service import PositionManagementService

            rule = PositionManagementRuleModel._default_manager.filter(id=rule_id).first()
            if not rule:
                return None
            return PositionManagementService.evaluate(rule=rule, context=context).to_dict()
        except Exception as e:
            logger.error(f"Error evaluating position rule: {e}")
            return None


# ============================================================================
# 全局单例
# ============================================================================

_gateway_instance: Optional[StrategyExecutionGateway] = None


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
