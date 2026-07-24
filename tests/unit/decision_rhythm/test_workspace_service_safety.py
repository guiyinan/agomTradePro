"""Workspace service risk-check safety regressions."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.decision_rhythm.application import workspace_services
from apps.decision_rhythm.domain.entities import (
    InvestmentRecommendation,
    PortfolioTransitionPlan,
    TransitionOrder,
)


class _FailingQuotaRepository:
    def get_quota(self, period: object) -> object:
        raise RuntimeError("quota unavailable")


class _FailingCooldownRepository:
    def get_active_cooldown(self, security_code: str) -> object:
        raise RuntimeError("cooldown unavailable")


def _recommendation() -> InvestmentRecommendation:
    return InvestmentRecommendation(
        recommendation_id="rec-risk",
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


def _plan() -> PortfolioTransitionPlan:
    order = TransitionOrder(
        security_code="000001.SH",
        action="BUY",
        current_qty=0,
        target_qty=100,
        delta_qty=100,
        current_weight=0.0,
        target_weight=0.1,
        price_band_low=Decimal("9"),
        price_band_high=Decimal("11"),
        max_capital=Decimal("10000"),
        stop_loss_price=Decimal("8"),
        invalidation_rule={"conditions": [{"field": "price"}]},
    )
    return PortfolioTransitionPlan(
        plan_id="plan-risk",
        account_id="default",
        as_of=datetime.now(UTC),
        source_recommendation_ids=["rec-risk"],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[order],
        risk_contract={},
        summary={},
    )


def test_recommendation_risk_dependencies_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workspace_services,
        "get_quota_repository",
        lambda: _FailingQuotaRepository(),
    )
    monkeypatch.setattr(
        workspace_services,
        "get_cooldown_repository",
        lambda: _FailingCooldownRepository(),
    )

    checks = workspace_services.build_recommendation_risk_checks(
        _recommendation(),
        Decimal("10"),
    )

    assert checks["quota"]["passed"] is False
    assert checks["cooldown"]["passed"] is False


def test_plan_cooldown_dependency_failure_blocks_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workspace_services,
        "get_quota_repository",
        lambda: _FailingQuotaRepository(),
    )
    monkeypatch.setattr(
        workspace_services,
        "get_cooldown_repository",
        lambda: _FailingCooldownRepository(),
    )

    checks = workspace_services.build_plan_risk_checks(_plan())

    assert checks["quota"]["passed"] is False
    assert checks["cooldown"]["passed"] is False
    assert "冷却检查失败" in checks["cooldown"]["reason"]
