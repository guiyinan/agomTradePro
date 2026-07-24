"""
Use Cases for Investment Signal Validation.

Application layer orchestrating the workflow of signal validation.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Protocol

from apps.regime.domain.asset_eligibility import (
    Eligibility,
    get_eligibility_matrix,
)

from ..domain.entities import InvestmentSignal, SignalStatus
from ..domain.indicators import find_indicator_by_alias
from ..domain.invalidation import (
    IndicatorValue,
    InvalidationCheckResult,
    evaluate_rule,
)
from ..domain.parser import InvalidationLogicParser
from ..domain.rules import (
    RejectionRecord,
    ValidationResult,
    should_reject_signal,
    validate_invalidation_logic,
)

logger = logging.getLogger(__name__)


class ReevaluateSignalRepositoryProtocol(Protocol):
    """Persistence operations required by signal reevaluation."""

    def get_active_signals(self) -> list[InvestmentSignal]: ...

    def update_signal_status(
        self,
        signal_id: str,
        new_status: SignalStatus,
        rejection_reason: str | None = None,
    ) -> bool: ...


class InvalidationCheckServiceProtocol(Protocol):
    """Side-effecting invalidation check used during reevaluation."""

    def check_signal_by_id(
        self,
        signal_id: int,
    ) -> InvalidationCheckResult | None: ...


@dataclass
class ValidateSignalRequest:
    """验证投资信号的请求 DTO"""

    asset_code: str
    asset_class: str
    direction: str
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: float | None
    target_regime: str
    current_regime: str
    policy_level: int
    regime_confidence: float


@dataclass
class ValidateSignalResponse:
    """验证投资信号的响应 DTO"""

    is_valid: bool
    is_approved: bool
    rejection_record: RejectionRecord | None
    logic_validation: ValidationResult
    errors: list[str]
    warnings: list[str]


class ValidateSignalUseCase:
    """
    验证投资信号的用例

    职责：
    1. 验证证伪逻辑完整性
    2. 检查准入规则
    3. 返回验证结果
    """

    def execute(self, request: ValidateSignalRequest) -> ValidateSignalResponse:
        """
        执行信号验证

        Args:
            request: 验证请求

        Returns:
            ValidateSignalResponse: 验证结果
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. 验证证伪逻辑
        logic_validation = validate_invalidation_logic(request.invalidation_logic)
        errors.extend(logic_validation.errors)
        warnings.extend(logic_validation.warnings)

        # 如果证伪逻辑无效，直接返回
        if not logic_validation.is_valid:
            return ValidateSignalResponse(
                is_valid=False,
                is_approved=False,
                rejection_record=None,
                logic_validation=logic_validation,
                errors=errors,
                warnings=warnings,
            )

        # 2. 检查是否应该拒绝信号
        should_reject, rejection_reason, eligibility = should_reject_signal(
            asset_class=request.asset_class,
            current_regime=request.current_regime,
            policy_level=request.policy_level,
            confidence=request.regime_confidence,
        )

        rejection_record = None
        if should_reject:
            if rejection_reason is None or eligibility is None:
                raise RuntimeError("Rejected signal is missing rejection evidence")
            rejection_record = RejectionRecord(
                asset_code=request.asset_code,
                asset_class=request.asset_class,
                current_regime=request.current_regime,
                eligibility=eligibility,
                reason=rejection_reason,
                policy_veto=(request.policy_level >= 3),
            )

        return ValidateSignalResponse(
            is_valid=True,
            is_approved=not should_reject,
            rejection_record=rejection_record,
            logic_validation=logic_validation,
            errors=errors,
            warnings=warnings,
        )

    def validate_and_create_signal(self, request: ValidateSignalRequest) -> InvestmentSignal | None:
        """
        验证并创建信号（如果通过）

        Args:
            request: 验证请求

        Returns:
            Optional[InvestmentSignal]: 如果通过则返回信号实体，否则返回 None
        """
        response = self.execute(request)

        if not response.is_valid or not response.is_approved:
            return None

        return InvestmentSignal(
            id=None,
            asset_code=request.asset_code,
            asset_class=request.asset_class,
            direction=request.direction,
            logic_desc=request.logic_desc,
            invalidation_logic=request.invalidation_logic,
            invalidation_threshold=request.invalidation_threshold,
            target_regime=request.target_regime,
            created_at=date.today(),
            status=SignalStatus.APPROVED,
        )


@dataclass
class CheckSignalInvalidationRequest:
    """检查信号证伪的请求 DTO"""

    signal: InvestmentSignal
    current_indicator_values: dict[str, float]


@dataclass
class CheckSignalInvalidationResponse:
    """检查信号证伪的响应 DTO"""

    is_invalidated: bool
    reason: str


class CheckSignalInvalidationUseCase:
    """
    检查投资信号是否应该被证伪的用例

    根据信号中定义的 invalidation_logic 判断当前状态是否满足证伪条件。
    """

    def execute(self, request: CheckSignalInvalidationRequest) -> CheckSignalInvalidationResponse:
        """
        执行证伪检查

        Args:
            request: 检查请求

        Returns:
            CheckSignalInvalidationResponse: 检查结果
        """
        rule = request.signal.invalidation_rule
        if rule is None:
            logic = (request.signal.invalidation_logic or "").strip()
            if not logic:
                return CheckSignalInvalidationResponse(
                    is_invalidated=False,
                    reason="信号没有可评估的证伪规则",
                )
            parse_result = InvalidationLogicParser().parse(logic)
            if not parse_result.success and request.signal.invalidation_threshold is not None:
                parse_result = InvalidationLogicParser().parse(
                    f"{logic} {request.signal.invalidation_threshold}"
                )
            if not parse_result.success or parse_result.rule is None:
                return CheckSignalInvalidationResponse(
                    is_invalidated=False,
                    reason="证伪规则无法解析",
                )
            rule = parse_result.rule

        indicator_values: dict[str, IndicatorValue] = {}
        for raw_code, raw_value in request.current_indicator_values.items():
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or not isfinite(float(raw_value))
            ):
                continue
            indicator = find_indicator_by_alias(raw_code)
            code = indicator.code if indicator is not None else raw_code.strip()
            if not code:
                continue
            indicator_values[code] = IndicatorValue(
                code=code,
                current_value=float(raw_value),
                history_values=[],
                unit="",
                last_updated=None,
            )

        result = evaluate_rule(rule, indicator_values)
        return CheckSignalInvalidationResponse(
            is_invalidated=result.is_invalidated,
            reason=result.reason,
        )


@dataclass
class GetRecommendedAssetsRequest:
    """获取推荐资产的请求 DTO"""

    current_regime: str


@dataclass
class GetRecommendedAssetsResponse:
    """获取推荐资产的响应 DTO"""

    recommended: list[str]
    neutral: list[str]
    hostile: list[str]


class GetRecommendedAssetsUseCase:
    """
    获取当前 Regime 下推荐资产的用例
    """

    def execute(self, request: GetRecommendedAssetsRequest) -> GetRecommendedAssetsResponse:
        """
        执行获取推荐资产

        Args:
            request: 请求

        Returns:
            GetRecommendedAssetsResponse: 推荐资产分类
        """
        recommended: list[str] = []
        neutral: list[str] = []
        hostile: list[str] = []

        eligibility_matrix = get_eligibility_matrix()
        for asset_class, regime_map in eligibility_matrix.items():
            eligibility = regime_map.get(request.current_regime, Eligibility.NEUTRAL)
            if eligibility == Eligibility.PREFERRED:
                recommended.append(asset_class)
            elif eligibility == Eligibility.NEUTRAL:
                neutral.append(asset_class)
            elif eligibility == Eligibility.HOSTILE:
                hostile.append(asset_class)

        return GetRecommendedAssetsResponse(
            recommended=recommended, neutral=neutral, hostile=hostile
        )


@dataclass
class ReevaluateSignalsRequest:
    """重评信号的请求 DTO"""

    policy_level: int
    current_regime: str | None = None
    regime_confidence: float = 0.0


@dataclass
class ReevaluateSignalsResponse:
    """重评信号的响应 DTO"""

    total_count: int
    rejected_count: int
    rejected_signal_ids: list[str]
    invalidated_count: int = 0
    invalidated_signal_ids: list[str] = field(default_factory=list)


class ReevaluateSignalsUseCase:
    """
    重评所有活跃信号的用例

    当政策档位变化时，重新评估所有活跃的信号是否应该被拒绝。
    同时检查信号自身的证伪条件是否满足。
    """

    def __init__(
        self,
        signal_repository: ReevaluateSignalRepositoryProtocol,
        invalidation_check_service: InvalidationCheckServiceProtocol | None = None,
    ) -> None:
        """
        Args:
            signal_repository: SignalRepository 实例
            invalidation_check_service: InvalidationCheckService 实例（可选）
        """
        self.signal_repository = signal_repository
        self.invalidation_check_service = invalidation_check_service

    def execute(self, request: ReevaluateSignalsRequest) -> ReevaluateSignalsResponse:
        """
        执行信号重评

        Args:
            request: 重评请求

        Returns:
            ReevaluateSignalsResponse: 重评结果
        """
        current_regime = (
            request.current_regime.strip() if isinstance(request.current_regime, str) else ""
        )
        if (
            isinstance(request.policy_level, bool)
            or not isinstance(request.policy_level, int)
            or not 0 <= request.policy_level <= 3
            or not current_regime
            or isinstance(request.regime_confidence, bool)
            or not isinstance(request.regime_confidence, (int, float))
            or not isfinite(float(request.regime_confidence))
            or not 0 <= request.regime_confidence <= 1
        ):
            raise ValueError("Signal reevaluation context is invalid")

        # 获取所有活跃信号
        active_signals = self.signal_repository.get_active_signals()

        rejected_count = 0
        rejected_signal_ids: list[str] = []
        invalidated_signal_ids: list[str] = []

        for signal in active_signals:
            signal_id = str(signal.id or "").strip()
            if not signal_id:
                raise ValueError("Active signal is missing a persisted identifier")

            # 1. 根据新的 policy_level 重评
            should_reject, reason, _eligibility = should_reject_signal(
                asset_class=signal.asset_class,
                current_regime=current_regime,
                policy_level=request.policy_level,
                confidence=request.regime_confidence,
            )

            if should_reject:
                reject_reason = f"Policy level change: {reason or 'rejected'}"
                updated = self.signal_repository.update_signal_status(
                    signal_id=signal_id,
                    new_status=SignalStatus.REJECTED,
                    rejection_reason=reject_reason,
                )
                if not updated:
                    raise RuntimeError(f"Failed to persist rejected signal {signal_id}")
                rejected_count += 1
                rejected_signal_ids.append(signal_id)
                logger.info(
                    "Signal %s (%s) rejected: %s",
                    signal_id,
                    signal.asset_code,
                    reject_reason,
                )
                continue

            # 2. InvalidationCheckService owns the INVALIDATED state transition.
            if self.invalidation_check_service is not None and (
                signal.invalidation_rule is not None or signal.invalidation_logic
            ):
                try:
                    numeric_signal_id = int(signal_id)
                except ValueError as exc:
                    raise ValueError(
                        "Invalidation check requires a numeric signal identifier"
                    ) from exc
                if numeric_signal_id <= 0:
                    raise ValueError("Invalidation check requires a positive signal identifier")
                invalidation_result = self.invalidation_check_service.check_signal_by_id(
                    numeric_signal_id
                )
                if invalidation_result and invalidation_result.is_invalidated:
                    invalidated_signal_ids.append(signal_id)
                    logger.info(
                        "Signal %s (%s) invalidated: %s",
                        signal_id,
                        signal.asset_code,
                        invalidation_result.reason,
                    )

        logger.info(
            f"Signal reevaluation completed: {rejected_count}/{len(active_signals)} signals rejected"
        )

        return ReevaluateSignalsResponse(
            total_count=len(active_signals),
            rejected_count=rejected_count,
            rejected_signal_ids=rejected_signal_ids,
            invalidated_count=len(invalidated_signal_ids),
            invalidated_signal_ids=invalidated_signal_ids,
        )
