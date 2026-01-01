"""
Use Cases for Investment Signal Validation.

Application layer orchestrating the workflow of signal validation.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, List

from ..domain.entities import InvestmentSignal, SignalStatus
from ..domain.rules import (
    validate_invalidation_logic,
    should_reject_signal,
    create_rejection_record,
    RejectionRecord,
    ValidationResult,
)


@dataclass
class ValidateSignalRequest:
    """验证投资信号的请求 DTO"""
    asset_code: str
    asset_class: str
    direction: str
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: Optional[float]
    target_regime: str
    current_regime: str
    policy_level: int
    regime_confidence: float


@dataclass
class ValidateSignalResponse:
    """验证投资信号的响应 DTO"""
    is_valid: bool
    is_approved: bool
    rejection_record: Optional[RejectionRecord]
    logic_validation: ValidationResult
    errors: List[str]
    warnings: List[str]


class ValidateSignalUseCase:
    """
    验证投资信号的用例

    职责：
    1. 验证证伪逻辑完整性
    2. 检查准入规则
    3. 返回验证结果
    """

    def __init__(self):
        pass

    def execute(self, request: ValidateSignalRequest) -> ValidateSignalResponse:
        """
        执行信号验证

        Args:
            request: 验证请求

        Returns:
            ValidateSignalResponse: 验证结果
        """
        errors = []
        warnings = []

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
                warnings=warnings
            )

        # 2. 检查是否应该拒绝信号
        should_reject, rejection_reason, eligibility = should_reject_signal(
            asset_class=request.asset_class,
            current_regime=request.current_regime,
            policy_level=request.policy_level,
            confidence=request.regime_confidence
        )

        rejection_record = None
        if should_reject:
            rejection_record = RejectionRecord(
                asset_code=request.asset_code,
                asset_class=request.asset_class,
                current_regime=request.current_regime,
                eligibility=eligibility,
                reason=rejection_reason,
                policy_veto=(request.policy_level >= 3)
            )

        return ValidateSignalResponse(
            is_valid=True,
            is_approved=not should_reject,
            rejection_record=rejection_record,
            logic_validation=logic_validation,
            errors=errors,
            warnings=warnings
        )

    def validate_and_create_signal(
        self,
        request: ValidateSignalRequest
    ) -> Optional[InvestmentSignal]:
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
            status=SignalStatus.APPROVED
        )


@dataclass
class CheckSignalInvalidationRequest:
    """检查信号证伪的请求 DTO"""
    signal: InvestmentSignal
    current_indicator_values: dict


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

    def __init__(self):
        pass

    def execute(
        self,
        request: CheckSignalInvalidationRequest
    ) -> CheckSignalInvalidationResponse:
        """
        执行证伪检查

        Args:
            request: 检查请求

        Returns:
            CheckSignalInvalidationResponse: 检查结果
        """
        logic = request.signal.invalidation_logic.lower()
        values = request.current_indicator_values

        # 简单的规则匹配（可扩展）
        if "跌破" in logic or "<" in logic:
            # 检查是否跌破阈值
            threshold = request.signal.invalidation_threshold
            if threshold is not None:
                # 假设主要指标是第一个值
                main_value = list(values.values())[0] if values else None
                if main_value is not None and main_value < threshold:
                    return CheckSignalInvalidationResponse(
                        is_invalidated=True,
                        reason=f"指标值 {main_value} 跌破阈值 {threshold}"
                    )

        if "突破" in logic or ">" in logic:
            # 检查是否突破阈值
            threshold = request.signal.invalidation_threshold
            if threshold is not None:
                main_value = list(values.values())[0] if values else None
                if main_value is not None and main_value > threshold:
                    return CheckSignalInvalidationResponse(
                        is_invalidated=True,
                        reason=f"指标值 {main_value} 突破阈值 {threshold}"
                    )

        # 如果没有阈值，进行简单的文本匹配
        for key, value in values.items():
            if key.lower() in logic:
                # 检查是否包含数字条件
                import re
                numbers = re.findall(r'\d+\.?\d*', logic)
                for num_str in numbers:
                    threshold = float(num_str)
                    if "<" in logic or "低于" in logic or "跌破" in logic:
                        if value < threshold:
                            return CheckSignalInvalidationResponse(
                                is_invalidated=True,
                                reason=f"{key}={value} 低于条件 {threshold}"
                            )
                    if ">" in logic or "高于" in logic or "突破" in logic:
                        if value > threshold:
                            return CheckSignalInvalidationResponse(
                                is_invalidated=True,
                                reason=f"{key}={value} 高于条件 {threshold}"
                            )

        return CheckSignalInvalidationResponse(
            is_invalidated=False,
            reason="未满足证伪条件"
        )


@dataclass
class GetRecommendedAssetsRequest:
    """获取推荐资产的请求 DTO"""
    current_regime: str


@dataclass
class GetRecommendedAssetsResponse:
    """获取推荐资产的响应 DTO"""
    recommended: List[str]
    neutral: List[str]
    hostile: List[str]


class GetRecommendedAssetsUseCase:
    """
    获取当前 Regime 下推荐资产的用例
    """

    def __init__(self):
        pass

    def execute(
        self,
        request: GetRecommendedAssetsRequest
    ) -> GetRecommendedAssetsResponse:
        """
        执行获取推荐资产

        Args:
            request: 请求

        Returns:
            GetRecommendedAssetsResponse: 推荐资产分类
        """
        from ..domain.rules import get_eligibility_matrix, Eligibility

        recommended = []
        neutral = []
        hostile = []

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
            recommended=recommended,
            neutral=neutral,
            hostile=hostile
        )


@dataclass
class ReevaluateSignalsRequest:
    """重评信号的请求 DTO"""
    policy_level: int
    current_regime: Optional[str] = None
    regime_confidence: float = 0.0


@dataclass
class ReevaluateSignalsResponse:
    """重评信号的响应 DTO"""
    total_count: int
    rejected_count: int
    rejected_signal_ids: List[str]


class ReevaluateSignalsUseCase:
    """
    重评所有活跃信号的用例

    当政策档位变化时，重新评估所有活跃的信号是否应该被拒绝。
    """

    def __init__(self, signal_repository):
        """
        Args:
            signal_repository: SignalRepository 实例
        """
        self.signal_repository = signal_repository

    def execute(self, request: ReevaluateSignalsRequest) -> ReevaluateSignalsResponse:
        """
        执行信号重评

        Args:
            request: 重评请求

        Returns:
            ReevaluateSignalsResponse: 重评结果
        """
        import logging
        logger = logging.getLogger(__name__)

        # 获取所有活跃信号
        active_signals = self.signal_repository.get_active_signals()

        rejected_count = 0
        rejected_signal_ids = []

        for signal in active_signals:
            # 根据新的 policy_level 重评
            current_regime = request.current_regime or signal.target_regime

            should_reject, reason, _ = should_reject_signal(
                asset_class=signal.asset_class,
                current_regime=current_regime,
                policy_level=request.policy_level,
                confidence=request.regime_confidence
            )

            if should_reject:
                # 更新信号状态
                self.signal_repository.update_signal_status(
                    signal_id=signal.id,
                    new_status=SignalStatus.REJECTED,
                    rejection_reason=reason
                )
                rejected_count += 1
                rejected_signal_ids.append(signal.id)

                logger.info(
                    f"Signal {signal.id} ({signal.asset_code}) rejected due to policy level change: {reason}"
                )

        logger.info(
            f"Signal reevaluation completed: {rejected_count}/{len(active_signals)} signals rejected"
        )

        return ReevaluateSignalsResponse(
            total_count=len(active_signals),
            rejected_count=rejected_count,
            rejected_signal_ids=rejected_signal_ids
        )
