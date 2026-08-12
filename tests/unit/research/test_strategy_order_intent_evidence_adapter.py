"""Tests for the fail-closed legacy Strategy order-intent adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.application.strategy_order_intent_evidence_adapter import (
    LegacyStrategyOrderIntentProjection,
    build_strategy_order_intent_legacy_evidence_summary,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)


def _projection() -> LegacyStrategyOrderIntentProjection:
    return LegacyStrategyOrderIntentProjection(
        intent_id="intent-001",
        strategy_id=7,
        portfolio_id=11,
        symbol="000001.SZ",
        side="buy",
        qty=100,
        limit_price=Decimal("12.50"),
        time_in_force="day",
        reason="Governed strategy preview.",
        idempotency_key="intent-001",
        status="draft",
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=1),
        decision_action="allow",
        decision_reason_codes=("regime.allowed", "risk.within_limits"),
        decision_reason_text="Regime and risk checks allow the preview.",
        decision_valid_until=NOW + timedelta(minutes=15),
        decision_confidence=Decimal("0.85"),
        sizing_target_notional=Decimal("1250.00"),
        sizing_qty=100,
        sizing_expected_risk_pct=Decimal("0.75"),
        sizing_method="fixed_risk",
        sizing_explain="Quantity is bounded by the configured risk budget.",
        risk_total_equity=Decimal("100000"),
        risk_cash_balance=Decimal("80000"),
        risk_total_position_value=Decimal("20000"),
        risk_daily_pnl_pct=Decimal("0.10"),
        risk_max_single_position_pct=Decimal("2.00"),
        risk_top3_position_pct=Decimal("12.00"),
        risk_current_regime="recovery",
        risk_regime_confidence=Decimal("0.80"),
        risk_volatility_index=Decimal("1.20"),
        risk_max_position_limit_pct=Decimal("20"),
        risk_daily_loss_limit_pct=Decimal("5"),
        risk_daily_trade_limit=10,
    )


def _summary(projection: LegacyStrategyOrderIntentProjection) -> EvidenceSummaryDTO:
    return build_strategy_order_intent_legacy_evidence_summary(projection, evaluated_at=NOW)


def test_order_intent_adapter_binds_every_business_field_and_is_display_only() -> None:
    baseline = _summary(_projection())
    changed_values = (
        replace(_projection(), qty=200, sizing_qty=200),
        replace(_projection(), limit_price=Decimal("12.51")),
        replace(_projection(), status="pending_approval"),
        replace(_projection(), decision_action="watch"),
        replace(_projection(), sizing_target_notional=Decimal("1251")),
        replace(_projection(), risk_cash_balance=Decimal("79999")),
    )

    assert baseline.output_owner == "strategy"
    assert baseline.output_artifact_type == "order_intent"
    assert baseline.output_artifact_id == "intent-001"
    assert baseline.output_artifact_version == (f"order-intent-v1.{baseline.output_content_hash}")
    assert baseline.claim_kind == "recommendation"
    assert baseline.method_kind == "deterministic"
    assert baseline.governance_state == "research_only"
    assert baseline.permission == "display_only"
    assert baseline.blocker_codes == ("evidence.legacy_unverified",)
    assert baseline.must_not_use_for_decision is True
    assert baseline.must_not_execute is True
    for changed in changed_values:
        summary = _summary(changed)
        assert summary.output_content_hash != baseline.output_content_hash
        assert summary.envelope_content_hash != baseline.envelope_content_hash


def test_order_intent_adapter_canonicalizes_equivalent_decimals_and_timezones() -> None:
    baseline = _summary(_projection())
    equivalent = replace(
        _projection(),
        limit_price=Decimal("12.5000"),
        created_at=_projection().created_at.astimezone(timezone(timedelta(hours=8))),
        updated_at=_projection().updated_at.astimezone(timezone(timedelta(hours=8))),
    )

    assert _summary(equivalent).output_content_hash == baseline.output_content_hash


def test_order_intent_status_transition_changes_hash_without_updated_at_change() -> None:
    draft = _summary(_projection())
    sent = _summary(replace(_projection(), status="sent"))

    assert sent.output_content_hash != draft.output_content_hash
    assert sent.output_artifact_version != draft.output_artifact_version


@pytest.mark.parametrize(
    "projection",
    [
        replace(_projection(), strategy_id=0),
        replace(_projection(), strategy_id=True),
        replace(_projection(), side="hold"),
        replace(_projection(), qty=0, sizing_qty=0),
        replace(_projection(), sizing_qty=99),
        replace(_projection(), decision_reason_codes=()),
        replace(
            _projection(),
            decision_reason_codes=("risk.z", "risk.a"),
        ),
        replace(_projection(), decision_valid_until=NOW),
        replace(_projection(), updated_at=NOW + timedelta(seconds=1)),
        replace(_projection(), decision_confidence=Decimal("NaN")),
        replace(_projection(), risk_total_equity=Decimal("0")),
        replace(_projection(), risk_regime_confidence=Decimal("1.01")),
        replace(_projection(), risk_daily_trade_limit=0),
        replace(_projection(), risk_daily_trade_limit=True),
    ],
)
def test_order_intent_adapter_rejects_unverifiable_projection(
    projection: LegacyStrategyOrderIntentProjection,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _summary(projection)


def test_order_intent_adapter_rejects_naive_evaluation_clock() -> None:
    with pytest.raises(ValueError, match="evaluated_at"):
        build_strategy_order_intent_legacy_evidence_summary(
            _projection(), evaluated_at=NOW.replace(tzinfo=None)
        )
