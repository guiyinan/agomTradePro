"""Safety contracts for signal validation and reevaluation use cases."""

from __future__ import annotations

from math import inf, nan

import pytest

from apps.signal.application.use_cases import (
    CheckSignalInvalidationRequest,
    CheckSignalInvalidationUseCase,
    ReevaluateSignalsRequest,
    ReevaluateSignalsUseCase,
    ValidateSignalRequest,
    ValidateSignalUseCase,
)
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.signal.domain.invalidation import (
    ComparisonOperator,
    IndicatorType,
    InvalidationCheckResult,
    InvalidationCondition,
)
from apps.signal.domain.parser import InvalidationLogicParser
from apps.signal.domain.rules import should_reject_signal


def _signal(
    *,
    signal_id: str | None = "7",
    logic: str | None = "PMI < 50",
    asset_class: str = "a_share_growth",
) -> InvestmentSignal:
    return InvestmentSignal(
        id=signal_id,
        asset_code="510300.SH",
        asset_class=asset_class,
        direction="LONG",
        logic_desc="PMI 回升，看好宽基指数",
        invalidation_logic=logic,
        invalidation_threshold=50.0,
        target_regime="Recovery",
        status=SignalStatus.APPROVED,
    )


@pytest.mark.parametrize(
    ("logic", "expected"),
    [
        ("PMI <= 50", ComparisonOperator.LTE),
        ("PMI >= 50", ComparisonOperator.GTE),
        ("PMI 低于等于 50", ComparisonOperator.LTE),
        ("PMI 高于等于 50", ComparisonOperator.GTE),
    ],
)
def test_parser_prefers_longest_comparison_operator(
    logic: str,
    expected: ComparisonOperator,
) -> None:
    result = InvalidationLogicParser().parse(logic)

    assert result.success
    assert result.rule is not None
    assert result.rule.conditions[0].operator is expected


def test_legacy_invalidation_uses_named_indicator_not_mapping_order() -> None:
    response = CheckSignalInvalidationUseCase().execute(
        CheckSignalInvalidationRequest(
            signal=_signal(),
            current_indicator_values={"CPI": 1.0, "PMI": 51.0},
        )
    )

    assert response.is_invalidated is False


def test_legacy_invalidation_evaluates_canonicalized_indicator() -> None:
    response = CheckSignalInvalidationUseCase().execute(
        CheckSignalInvalidationRequest(
            signal=_signal(),
            current_indicator_values={"PMI": 49.0},
        )
    )

    assert response.is_invalidated is True
    assert "CN_PMI_MANUFACTURING=49.0" in response.reason


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_legacy_invalidation_ignores_non_finite_observation(
    value: float,
) -> None:
    response = CheckSignalInvalidationUseCase().execute(
        CheckSignalInvalidationRequest(
            signal=_signal(),
            current_indicator_values={"PMI": value},
        )
    )

    assert response.is_invalidated is False


@pytest.mark.parametrize("threshold", [nan, inf, -inf, True])
def test_invalidation_condition_rejects_invalid_threshold(
    threshold: float,
) -> None:
    with pytest.raises(ValueError, match="有限数值"):
        InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=threshold,
        )


@pytest.mark.parametrize(
    ("current_regime", "policy_level", "confidence"),
    [
        ("Unknown", 0, 0.8),
        ("Recovery", -1, 0.8),
        ("Recovery", 4, 0.8),
        ("Recovery", 0, nan),
        ("Recovery", 0, 1.1),
    ],
)
def test_signal_rejection_fails_closed_on_invalid_context(
    current_regime: str,
    policy_level: int,
    confidence: float,
) -> None:
    rejected, reason, _eligibility = should_reject_signal(
        asset_class="a_share_growth",
        current_regime=current_regime,
        policy_level=policy_level,
        confidence=confidence,
    )

    assert rejected is True
    assert reason is not None
    assert "无效" in reason


def test_validate_signal_does_not_approve_invalid_context() -> None:
    response = ValidateSignalUseCase().execute(
        ValidateSignalRequest(
            asset_code="510300.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="PMI 回升，看好宽基指数",
            invalidation_logic="PMI 跌破 50 且持续恶化",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            current_regime="Unknown",
            policy_level=0,
            regime_confidence=0.8,
        )
    )

    assert response.is_valid is True
    assert response.is_approved is False
    assert response.rejection_record is not None


class _Repository:
    def __init__(self, signals: list[InvestmentSignal], *, update_result: bool = True) -> None:
        self.signals = signals
        self.update_result = update_result
        self.updates: list[tuple[str, SignalStatus, str | None]] = []

    def get_active_signals(self) -> list[InvestmentSignal]:
        return self.signals

    def update_signal_status(
        self,
        signal_id: str,
        new_status: SignalStatus,
        rejection_reason: str | None = None,
    ) -> bool:
        self.updates.append((signal_id, new_status, rejection_reason))
        return self.update_result


class _InvalidatedService:
    def check_signal_by_id(self, signal_id: int) -> InvalidationCheckResult:
        assert signal_id == 7
        return InvalidationCheckResult(
            is_invalidated=True,
            reason="证伪条件满足",
            checked_conditions=[],
            checked_at="2026-07-25T00:00:00+00:00",
        )


class _FailingInvalidationService:
    def check_signal_by_id(self, signal_id: int) -> InvalidationCheckResult:
        raise RuntimeError(f"indicator source failed for {signal_id}")


def test_reevaluation_does_not_overwrite_invalidated_state_as_rejected() -> None:
    repository = _Repository([_signal()])
    response = ReevaluateSignalsUseCase(
        signal_repository=repository,
        invalidation_check_service=_InvalidatedService(),
    ).execute(
        ReevaluateSignalsRequest(
            policy_level=0,
            current_regime="Recovery",
            regime_confidence=0.8,
        )
    )

    assert repository.updates == []
    assert response.rejected_count == 0
    assert response.invalidated_count == 1
    assert response.invalidated_signal_ids == ["7"]


def test_reevaluation_does_not_hide_invalidation_check_failure() -> None:
    repository = _Repository([_signal()])

    with pytest.raises(RuntimeError, match="indicator source failed"):
        ReevaluateSignalsUseCase(
            signal_repository=repository,
            invalidation_check_service=_FailingInvalidationService(),
        ).execute(
            ReevaluateSignalsRequest(
                policy_level=0,
                current_regime="Recovery",
                regime_confidence=0.8,
            )
        )

    assert repository.updates == []


def test_reevaluation_fails_when_rejection_cannot_be_persisted() -> None:
    repository = _Repository([_signal()], update_result=False)

    with pytest.raises(RuntimeError, match="persist"):
        ReevaluateSignalsUseCase(repository).execute(
            ReevaluateSignalsRequest(
                policy_level=3,
                current_regime="Recovery",
                regime_confidence=0.8,
            )
        )


def test_reevaluation_rejects_invalid_context_before_repository_access() -> None:
    class _NeverCalledRepository(_Repository):
        def get_active_signals(self) -> list[InvestmentSignal]:
            raise AssertionError("repository must not be called")

    with pytest.raises(ValueError, match="context"):
        ReevaluateSignalsUseCase(_NeverCalledRepository([])).execute(
            ReevaluateSignalsRequest(
                policy_level=0,
                current_regime=None,
                regime_confidence=0.8,
            )
        )
