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

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Any, Literal, Protocol

from apps.strategy.application.inspection_risk_contracts import StrategyRiskLimitField
from apps.strategy.application.interface_contracts import (
    StrategyExecutionRunnerProtocol,
)
from apps.strategy.application.repository_provider import (
    build_strategy_executor,
    get_strategy_gateway_repository,
)
from core.exceptions import AgomTradeProException, ExternalServiceError

logger = __import__("logging").getLogger(__name__)


# ============================================================================
# Data Transfer Objects
# ============================================================================


StrategySelectionState = Literal["configured", "confirmed_unconfigured", "unavailable"]


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """策略执行结果"""

    success: bool
    signals: list[SignalInfo]
    error_message: str | None = None
    execution_time: datetime | None = None


@dataclass(frozen=True)
class InspectionSelection:
    """巡检所需的策略与仓位规则摘要。"""

    strategy_id: int | None
    position_rule_id: int | None
    rule_metadata: dict[str, Any]
    strategy_name: str | None = None
    strategy_type: str | None = None
    strategy_version: int | None = None
    rule_name: str | None = None
    max_position_pct: float | None = None
    max_total_position_pct: float | None = None
    stop_loss_pct: float | None = None
    selection_state: StrategySelectionState = "unavailable"
    position_rule_source_json: str | None = None
    risk_source_invalid_fields: tuple[StrategyRiskLimitField, ...] = ()

    @property
    def validated_selection_state(self) -> StrategySelectionState:
        """Reject state markers that conflict with the copied strategy evidence."""

        if type(self.selection_state) is not str:
            return "unavailable"
        if self.selection_state == "configured":
            allowed_risk_fields = {
                "max_single_position_pct",
                "max_total_position_pct",
                "stop_loss_pct",
            }
            invalid_fields = self.risk_source_invalid_fields
            if (
                type(invalid_fields) is not tuple
                or any(
                    type(field_name) is not str or field_name not in allowed_risk_fields
                    for field_name in invalid_fields
                )
                or len(invalid_fields) != len(set(invalid_fields))
            ):
                return "unavailable"
            optional_text = (
                self.strategy_name,
                self.strategy_type,
                self.rule_name,
            )
            optional_numbers = (
                self.max_position_pct,
                self.max_total_position_pct,
                self.stop_loss_pct,
            )
            if (
                type(self.strategy_id) is not int
                or self.strategy_id <= 0
                or self.position_rule_id is not None
                and (type(self.position_rule_id) is not int or self.position_rule_id <= 0)
                or self.strategy_version is not None
                and (type(self.strategy_version) is not int or self.strategy_version <= 0)
                or any(value is not None and type(value) is not str for value in optional_text)
                or any(
                    value is not None
                    and (
                        type(value) not in (int, float)
                        or not isfinite(value)
                        or value < 0
                        or value > 100
                    )
                    and field_name not in invalid_fields
                    for field_name, value in zip(
                        (
                            "max_single_position_pct",
                            "max_total_position_pct",
                            "stop_loss_pct",
                        ),
                        optional_numbers,
                        strict=True,
                    )
                )
                or self.max_position_pct is None
                and "max_single_position_pct" not in invalid_fields
                or self.max_total_position_pct is None
                and "max_total_position_pct" not in invalid_fields
                or type(self.rule_metadata) is not dict
                or any(type(key) is not str for key in self.rule_metadata)
                or self.position_rule_source_json is not None
                and type(self.position_rule_source_json) is not str
                or self.position_rule_source_json is not None
                and self.position_rule_id is None
            ):
                return "unavailable"
            return "configured"
        if self.selection_state == "confirmed_unconfigured":
            selection_fields = (
                self.strategy_id,
                self.position_rule_id,
                self.strategy_name,
                self.strategy_type,
                self.strategy_version,
                self.rule_name,
                self.max_position_pct,
                self.max_total_position_pct,
                self.stop_loss_pct,
            )
            if (
                type(self.rule_metadata) is dict
                and not self.rule_metadata
                and all(value is None for value in selection_fields)
                and self.position_rule_source_json is None
                and not self.risk_source_invalid_fields
            ):
                return "confirmed_unconfigured"
        return "unavailable"


# ============================================================================
# Gateway Protocol
# ============================================================================


class StrategyGatewayQueryProtocol(Protocol):
    """策略只读查询协议。"""

    def get_strategy_info(self, strategy_id: int) -> dict[str, Any] | None: ...

    def get_active_strategy_binding(self, account_id: int) -> dict[str, Any] | None: ...

    def get_inspection_selection(
        self,
        account_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection: ...

    def get_profile_scoped_inspection_selection(
        self,
        account_id: int,
        owner_profile_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """Return only strategy content allowed by the existing owner-profile scope."""
        ...

    def evaluate_position_rule(
        self,
        rule_id: int | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None: ...


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
        executor: StrategyExecutionRunnerProtocol | None = None,
        query_repository: StrategyGatewayQueryProtocol | None = None,
    ):
        """
        初始化网关

        Args:
            executor: 策略执行器 (可选， 支持依赖注入)
        """
        self._executor = executor
        self._query_repository = query_repository

    def _get_executor(self) -> StrategyExecutionRunnerProtocol:
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
        self, strategy_id: int, account_id: int, as_of_date: date | None = None
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
                    error_message=raw_result.error_message or "策略执行失败",
                )

            # 转换信号（StrategyExecutionResult.signals -> [SignalRecommendation]）
            signals = []
            for sig in raw_result.signals:
                signals.append(
                    SignalInfo(
                        signal_id=None,
                        asset_code=sig.asset_code,
                        asset_name=sig.asset_name,
                        action=(
                            sig.action.value if hasattr(sig.action, "value") else str(sig.action)
                        ),
                        quantity=sig.quantity,
                        confidence=sig.confidence,
                        reason=sig.reason,
                        metadata=dict(getattr(sig, "metadata", {}) or {}),
                    )
                )

            return ExecutionResult(
                success=True,
                signals=signals,
                execution_time=raw_result.execution_time,
            )

        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")
            return ExecutionResult(success=False, signals=[], error_message=str(e))

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
        except AgomTradeProException:
            raise
        except Exception as error:
            logger.error(
                "Active strategy binding lookup failed for account %s (error_type=%s)",
                account_id,
                type(error).__name__,
            )
            raise ExternalServiceError(
                "策略绑定信息暂不可用",
                code="STRATEGY_BINDING_UNAVAILABLE",
            ) from error

    def is_strategy_active(self, strategy_id: int) -> bool:
        """
        检查策略是否活跃

        Args:
            strategy_id: 策略 ID

        Returns:
            是否活跃
        """
        info = self.get_strategy_info(strategy_id)
        return info is not None and info.get("is_active", False)

    def get_inspection_selection(
        self,
        account_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """获取日更巡检需要的策略和规则信息。"""
        try:
            selection = self._get_query_repository().get_inspection_selection(
                account_id=account_id,
                strategy_id=strategy_id,
            )
        except Exception as e:
            logger.error(f"Error getting inspection selection: {e}")
            return _unavailable_inspection_selection()
        if type(selection) is not InspectionSelection:
            return _unavailable_inspection_selection()
        state = selection.validated_selection_state
        if state == "unavailable":
            return _unavailable_inspection_selection()
        return InspectionSelection(
            strategy_id=selection.strategy_id,
            position_rule_id=selection.position_rule_id,
            rule_metadata=selection.rule_metadata,
            strategy_name=selection.strategy_name,
            strategy_type=selection.strategy_type,
            strategy_version=selection.strategy_version,
            rule_name=selection.rule_name,
            max_position_pct=selection.max_position_pct,
            max_total_position_pct=selection.max_total_position_pct,
            stop_loss_pct=selection.stop_loss_pct,
            selection_state=state,
            position_rule_source_json=selection.position_rule_source_json,
            risk_source_invalid_fields=selection.risk_source_invalid_fields,
        )

    def get_profile_scoped_inspection_selection(
        self,
        account_id: int,
        owner_profile_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """Read rule content only for a strategy in this AccountProfile's owner scope."""

        if type(owner_profile_id) is not int or owner_profile_id <= 0:
            return _unavailable_inspection_selection()
        try:
            selection = self._get_query_repository().get_profile_scoped_inspection_selection(
                account_id=account_id,
                owner_profile_id=owner_profile_id,
                strategy_id=strategy_id,
            )
        except Exception as error:
            logger.error(
                "Owner strategy selection lookup failed for account %s (error_type=%s)",
                account_id,
                type(error).__name__,
            )
            return _unavailable_inspection_selection()
        if type(selection) is not InspectionSelection:
            return _unavailable_inspection_selection()
        if selection.validated_selection_state == "unavailable":
            return _unavailable_inspection_selection()
        return InspectionSelection(
            strategy_id=selection.strategy_id,
            position_rule_id=selection.position_rule_id,
            rule_metadata=selection.rule_metadata,
            strategy_name=selection.strategy_name,
            strategy_type=selection.strategy_type,
            strategy_version=selection.strategy_version,
            rule_name=selection.rule_name,
            max_position_pct=selection.max_position_pct,
            max_total_position_pct=selection.max_total_position_pct,
            stop_loss_pct=selection.stop_loss_pct,
            selection_state=selection.validated_selection_state,
            position_rule_source_json=selection.position_rule_source_json,
            risk_source_invalid_fields=selection.risk_source_invalid_fields,
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


def _unavailable_inspection_selection() -> InspectionSelection:
    """Return a clean restrictive DTO after a malformed or failed lookup."""

    return InspectionSelection(
        strategy_id=None,
        position_rule_id=None,
        rule_metadata={},
        selection_state="unavailable",
    )


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
