"""Decision workspace use-case safety regressions."""

from datetime import UTC, datetime
from decimal import Decimal

from apps.decision_rhythm.application.decision_workspace_use_cases import (
    ApproveExecutionRequest,
    ApproveExecutionUseCase,
    PreviewExecutionUseCase,
)
from apps.decision_rhythm.domain.entities import (
    ApprovalStatus,
    ExecutionApprovalRequest,
    InvestmentRecommendation,
)


def _recommendation() -> InvestmentRecommendation:
    """Build a recommendation for risk-check tests."""
    return InvestmentRecommendation(
        recommendation_id="rec-1",
        security_code="000001.SH",
        side="BUY",
        confidence=0.8,
        valuation_method="COMPOSITE",
        fair_value=Decimal("10"),
        entry_price_low=Decimal("9"),
        entry_price_high=Decimal("11"),
        target_price_low=Decimal("12"),
        target_price_high=Decimal("13"),
        stop_loss_price=Decimal("8"),
        position_size_pct=5.0,
        max_capital=Decimal("10000"),
        reason_codes=[],
        human_readable_rationale="test",
        account_id="default",
        valuation_snapshot_id="snapshot-1",
        source_recommendation_ids=[],
        created_at=datetime.now(UTC),
    )


class _FailingQuotaRepository:
    def get_quota(self, period: object) -> object:
        raise RuntimeError("quota unavailable")


class _FailingCooldownRepository:
    def get_active_cooldown(self, security_code: str) -> object:
        raise RuntimeError("cooldown unavailable")


def test_risk_provider_failures_block_preview() -> None:
    """Unavailable quota or cooldown evidence must fail closed."""
    use_case = PreviewExecutionUseCase(
        recommendation_repo=object(),
        approval_repo=object(),
        quota_repo=_FailingQuotaRepository(),
        cooldown_repo=_FailingCooldownRepository(),
    )

    checks = use_case._run_risk_checks(_recommendation(), Decimal("10"))

    assert checks["quota"]["passed"] is False
    assert checks["cooldown"]["passed"] is False


class _ApprovalRepository:
    def __init__(self, approval: ExecutionApprovalRequest) -> None:
        self.approval = approval

    def get_by_id(self, request_id: str) -> ExecutionApprovalRequest:
        return self.approval

    def save(self, approval_request: ExecutionApprovalRequest) -> ExecutionApprovalRequest:
        raise AssertionError("invalid zero-price approval must not be saved")


class _RejectingApprovalService:
    def can_approve(
        self,
        approval_request: ExecutionApprovalRequest,
        market_price: Decimal,
    ) -> tuple[bool, str]:
        assert market_price == Decimal("0.0")
        return False, "price must be positive"


def test_zero_market_price_is_validated_instead_of_skipped() -> None:
    """A supplied zero price must enter approval validation."""
    approval = ExecutionApprovalRequest(
        request_id="approval-1",
        recommendation_id="rec-1",
        plan_id=None,
        account_id="default",
        security_code="000001.SH",
        side="BUY",
        approval_status=ApprovalStatus.PENDING,
        suggested_quantity=100,
        market_price_at_review=None,
        price_range_low=Decimal("9"),
        price_range_high=Decimal("11"),
        stop_loss_price=Decimal("8"),
        risk_check_results={},
        reviewer_comments="",
        regime_source="test",
        created_at=datetime.now(UTC),
    )
    use_case = ApproveExecutionUseCase(
        approval_repo=_ApprovalRepository(approval),
        approval_service=_RejectingApprovalService(),
    )

    response = use_case.execute(
        ApproveExecutionRequest(
            approval_request_id=approval.request_id,
            reviewer_comments="approve",
            market_price=0.0,
        )
    )

    assert response.success is False
    assert response.error == "无法批准: price must be positive"
