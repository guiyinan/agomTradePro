"""Decision recommendation persistence regressions."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.decision_rhythm.domain.entities import InvestmentRecommendation
from apps.decision_rhythm.infrastructure.models import (
    InvestmentRecommendationModel,
    UnifiedRecommendationModel,
    ValuationSnapshotModel,
)
from apps.decision_rhythm.infrastructure.repositories import (
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
)

pytestmark = pytest.mark.django_db


def _recommendation(snapshot_id: str) -> InvestmentRecommendation:
    """Build a recommendation linked to the supplied valuation snapshot."""
    return InvestmentRecommendation(
        recommendation_id="rec-persistence",
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
        valuation_snapshot_id=snapshot_id,
        source_recommendation_ids=[],
        created_at=datetime.now(UTC),
    )


def test_missing_valuation_snapshot_is_not_silently_discarded() -> None:
    """Recommendation traceability must fail when its snapshot is absent."""
    repository = InvestmentRecommendationRepository()

    with pytest.raises(ValueError, match="Valuation snapshot not found"):
        repository.save(_recommendation("missing-snapshot"))


def test_recommendation_lists_fetch_snapshot_in_one_query(
    django_assert_num_queries: Callable[[int], AbstractContextManager[None]],
) -> None:
    """List mapping must not issue one snapshot query per recommendation."""
    snapshot = ValuationSnapshotModel.objects.create(
        snapshot_id="snapshot-query-count",
        security_code="000001.SH",
        valuation_method="COMPOSITE",
        fair_value=Decimal("10"),
        entry_price_low=Decimal("9"),
        entry_price_high=Decimal("11"),
        target_price_low=Decimal("12"),
        target_price_high=Decimal("13"),
        stop_loss_price=Decimal("8"),
        calculated_at=datetime.now(UTC),
        input_parameters={},
    )
    for index in range(2):
        InvestmentRecommendationModel.objects.create(
            recommendation_id=f"rec-query-{index}",
            security_code=f"00000{index + 1}.SH",
            account_id="default",
            side="BUY",
            confidence=0.8,
            valuation_method="COMPOSITE",
            fair_value=Decimal("10"),
            entry_price_low=Decimal("9"),
            entry_price_high=Decimal("11"),
            target_price_low=Decimal("12"),
            target_price_high=Decimal("13"),
            stop_loss_price=Decimal("8"),
            valuation_snapshot=snapshot,
        )

    repository = InvestmentRecommendationRepository()
    with django_assert_num_queries(1):
        recommendations = repository.get_active_recommendations()

    assert [item.valuation_snapshot_id for item in recommendations] == [
        snapshot.snapshot_id,
        snapshot.snapshot_id,
    ]


def test_zero_quantity_recommendation_cannot_enter_approval() -> None:
    """Approval creation must reject a recommendation with no executable quantity."""
    model = UnifiedRecommendationModel.objects.create(
        recommendation_id="urec-zero-quantity",
        account_id="default",
        security_code="000001.SH",
        side="BUY",
    )
    repository = ExecutionApprovalRequestRepository()

    with pytest.raises(ValueError, match="no executable quantity"):
        repository.create_for_unified_recommendation(
            model.to_domain(),
            account_id="default",
            risk_checks={},
            regime_source="test",
            market_price=Decimal("0"),
        )
