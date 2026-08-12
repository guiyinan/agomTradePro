"""Execution preview contracts must remain current-data and display-only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.strategy.application.execution_preview import (
    ExecutionPreviewPolicy,
    ExecutionPreviewRequest,
    evaluate_execution_preview,
)

NOW = datetime(2026, 8, 13, 11, tzinfo=UTC)


def _policy() -> ExecutionPreviewPolicy:
    return ExecutionPreviewPolicy(
        signal_threshold=0.6,
        confidence_threshold=0.7,
        regime_alignment_required=True,
        max_daily_loss_pct=5.0,
        max_daily_trades=10,
        sizing_method="fixed_fraction",
        risk_per_trade_pct=1.0,
        sizing_max_position_pct=20.0,
        risk_max_single_position_pct=20.0,
        min_qty=1,
        min_volume=100_000,
        market_max_age_seconds=300,
        signal_max_age_seconds=900,
        regime_max_age_seconds=86_400,
        account_max_age_seconds=300,
    )


def _request() -> ExecutionPreviewRequest:
    return ExecutionPreviewRequest(
        symbol="000001.SZ",
        side="buy",
        current_price=12.5,
        signal_strength=0.9,
        signal_direction="bullish",
        signal_confidence=0.85,
        current_regime="recovery",
        regime_confidence=0.8,
        account_equity=100_000.0,
        current_position_value=5_000.0,
        daily_pnl_pct=0.1,
        daily_trade_count=1,
        market_observed_at=NOW - timedelta(seconds=30),
        signal_observed_at=NOW - timedelta(minutes=2),
        regime_observed_at=NOW - timedelta(hours=1),
        account_observed_at=NOW - timedelta(seconds=45),
        stop_loss_price=11.5,
        target_regime="recovery",
        avg_volume=200_000.0,
    )


def test_allowing_domain_preview_is_still_display_only_and_non_executable() -> None:
    result = evaluate_execution_preview(_request(), policy=_policy(), evaluated_at=NOW)
    payload = result.to_payload()

    assert result.decision_action == "allow"
    assert result.risk_snapshot["passed"] is True
    assert result.can_execute is False
    assert result.research_only is True
    assert result.governance_state == "research_only"
    assert result.permission == "display_only"
    assert result.blocker_codes == (
        "evidence.not_integrated",
        "strategy.execution_preview.display_only",
    )
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert payload["market_observed_at"] == "2026-08-13T10:59:30Z"
    assert payload["can_execute"] is False


@pytest.mark.parametrize(
    ("field_name", "maximum_age"),
    [
        ("market_observed_at", 300),
        ("signal_observed_at", 900),
        ("regime_observed_at", 86_400),
        ("account_observed_at", 300),
    ],
)
def test_preview_rejects_each_stale_source_snapshot(field_name: str, maximum_age: int) -> None:
    request = replace(_request(), **{field_name: NOW - timedelta(seconds=maximum_age + 1)})

    with pytest.raises(ValueError, match="stale"):
        evaluate_execution_preview(request, policy=_policy(), evaluated_at=NOW)


def test_preview_rejects_future_or_naive_source_clocks() -> None:
    invalid = (
        replace(_request(), market_observed_at=NOW + timedelta(seconds=1)),
        replace(_request(), signal_observed_at=NOW.replace(tzinfo=None)),
    )
    for request in invalid:
        with pytest.raises(ValueError):
            evaluate_execution_preview(request, policy=_policy(), evaluated_at=NOW)


def test_preview_uses_caller_regime_instead_of_target_or_constant_confidence() -> None:
    mismatched = evaluate_execution_preview(
        replace(_request(), current_regime="stagflation"),
        policy=_policy(),
        evaluated_at=NOW,
    )
    low_confidence = evaluate_execution_preview(
        replace(_request(), target_regime=None, regime_confidence=0.4),
        policy=_policy(),
        evaluated_at=NOW,
    )

    assert mismatched.decision_action == "deny"
    assert mismatched.decision_reasons == ("REGIME_MISMATCH",)
    assert low_confidence.decision_action == "watch"
    assert low_confidence.can_execute is False


def test_preview_rejects_missing_or_nonfinite_current_facts() -> None:
    invalid = (
        replace(_request(), current_price=float("nan")),
        replace(_request(), current_price=0.0),
        replace(_request(), current_regime=""),
        replace(_request(), regime_confidence=1.01),
    )
    for request in invalid:
        with pytest.raises(ValueError):
            evaluate_execution_preview(request, policy=_policy(), evaluated_at=NOW)
