"""Additional business-edge coverage for the Equity forecast Domain."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.equity.domain.forecast_baseline import (
    BaselineCostRule,
    CostApplicability,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastErrorMetric,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
    PairedForecastBaselineRow,
    TieBreakRule,
)
from apps.equity.domain.forecast_baseline_evidence import (
    ForecastCalendarPeriod,
    ForecastPeriodHorizon,
    _require_aware,
    _require_finite,
    _require_sha256,
    _require_token,
)
from apps.equity.domain.forecast_baseline_trial import (
    InvalidationRuleOutcome,
    TrialMetricComparison,
    _calculate_invalidation_outcomes,
    _matches_invalidation,
    _row_error,
    _summarize_metric_comparisons,
)
from tests.unit.equity.test_forecast_baseline import (
    NOW,
    PERIODS,
    H,
    _actual,
    _actual_manifest,
    _artifact,
    _calendar_schedule,
    _forecast,
    _paired_rows,
    _period_horizon,
    _pit_input,
    _prediction,
    _result,
    _spec,
)


def _valid_result() -> tuple[
    ForecastBaselineTrialResult,
    ForecastBaselineSpec,
    ForecastBaselineArtifact,
    tuple[PairedForecastBaselineRow, ...],
]:
    spec = _spec()
    artifact = _artifact(spec)
    rows = _paired_rows()
    return _result(spec, artifact, rows), spec, artifact, rows


def test_evaluation_policy_rejects_collapsed_authority_window() -> None:
    """A forecast-freeze deadline must precede policy expiry."""

    policy = _spec().evaluation_policy
    with pytest.raises(ValueError, match="time window"):
        replace(policy, valid_until=policy.forecast_submission_deadline_at)


def test_research_authorization_rejects_invalid_scope_and_windows() -> None:
    """Research authorization must be scoped, active, and registered in advance."""

    result, _, _, _ = _valid_result()
    authorization = result.research_trial
    cases: tuple[dict[str, object], ...] = (
        {"owner": "equity"},
        {"valid_until": authorization.activated_at},
        {"baseline_spec_approved_at": authorization.forecast_origin_at + timedelta(days=1)},
        {"expected_period_ends": ()},
        {"metric_codes": ()},
    )
    for mutations in cases:
        with pytest.raises(ValueError):
            replace(authorization, **mutations)


def test_actual_manifest_rejects_non_authoritative_completeness_claims() -> None:
    """Evaluation actuals must be public, complete, timely, and independently owned."""

    manifest = _actual_manifest(_paired_rows())
    cases: tuple[dict[str, object], ...] = (
        {"owner": "equity"},
        {"knowledge_scope": "private"},
        {"as_of_time": manifest.produced_at + timedelta(seconds=1)},
        {"is_verified": False},
        {"missing_count": 1},
        {"selected_versions": ()},
        {"selected_versions_hash": "0" * 64},
        {"seal_hash": "0" * 64},
    )
    for mutations in cases:
        with pytest.raises(ValueError):
            replace(manifest, **mutations)


def test_forecast_evidence_rejects_identity_and_timing_substitution() -> None:
    """A forecast reference cannot substitute owners, horizons, versions, or time."""

    forecast = _forecast(0)
    cases: tuple[dict[str, object], ...] = (
        {"template_owner": "equity"},
        {"candidate_scenario": "base"},
        {"horizon_quarters": 0},
        {"metric_values": ()},
        {"forecast_version": 0},
        {"persisted_at": forecast.as_of_time - timedelta(seconds=1)},
        {"target_period_end": forecast.as_of_time.date() - timedelta(days=1)},
        {"period_horizon": _period_horizon(1)},
        {"sensitivity_artifacts": ()},
    )
    for mutations in cases:
        with pytest.raises(ValueError):
            replace(forecast, **mutations)

    sensitivity = forecast.sensitivity_artifacts[0]
    with pytest.raises(ValueError, match="owner"):
        replace(sensitivity, owner="equity")


def test_baseline_prediction_rejects_pre_effective_availability() -> None:
    """Baseline source evidence cannot become available before it exists."""

    prediction = _prediction(PERIODS[0], "revenue", "100", 0)
    with pytest.raises(ValueError, match="before effective"):
        replace(prediction, available_at=prediction.effective_at - timedelta(seconds=1))


def test_trial_value_objects_reject_incoherent_results() -> None:
    """Sealed comparison and invalidation outcomes must be internally consistent."""

    row = _paired_rows()[0]
    with pytest.raises(ValueError, match="key must match"):
        replace(row, metric_code="revenue")

    comparison = TrialMetricComparison(
        metric_code="revenue",
        error_metric=ForecastErrorMetric.MAE,
        forecast_error=Decimal("1"),
        baseline_error=Decimal("2"),
        improvement=Decimal("1"),
        sample_count=2,
        coverage=Decimal("1"),
        passes=True,
        reason_codes=(),
    )
    comparison_cases: tuple[dict[str, object], ...] = (
        {"forecast_error": Decimal("-1")},
        {"sample_count": True},
        {"coverage": Decimal("1.1")},
        {"passes": False},
    )
    for mutations in comparison_cases:
        with pytest.raises(ValueError):
            replace(comparison, **mutations)

    outcome = InvalidationRuleOutcome(
        rule_code="revenue_break",
        metric_code="revenue",
        operator=InvalidationOperator.GREATER_THAN,
        threshold=Decimal("5"),
        consecutive_periods=2,
        observed_errors=((PERIODS[0], Decimal("1")), (PERIODS[1], Decimal("2"))),
        triggered_at=None,
        passes=True,
        reason_codes=(),
    )
    outcome_cases: tuple[dict[str, object], ...] = (
        {"consecutive_periods": 0},
        {"observed_errors": tuple(reversed(outcome.observed_errors))},
        {"observed_errors": ((PERIODS[0], Decimal("-1")),)},
        {"passes": False},
    )
    for mutations in outcome_cases:
        with pytest.raises(ValueError):
            replace(outcome, **mutations)


def test_trial_creation_and_seal_reject_invalid_authority() -> None:
    """Trial creation and reconstruction must fail closed on authority drift."""

    result, spec, artifact, rows = _valid_result()
    applicable_cost = BaselineCostRule(
        applicability=CostApplicability.APPLICABLE,
        cost_model_version="cost.v1",
        cost_model_content_hash=H,
        not_applicable_reason="",
    )
    cost_spec = _spec(cost_rule=applicable_cost)
    with pytest.raises(ValueError, match="executed cost evidence"):
        _result(cost_spec, _artifact(cost_spec), rows)
    with pytest.raises(ValueError, match="trial validity"):
        _result(spec, artifact, rows, valid_until=NOW)

    result_cases: tuple[dict[str, object], ...] = (
        {"owner": "research"},
        {
            "research_trial": replace(
                result.research_trial,
                baseline_spec_id="different-spec",
            )
        },
        {"valid_until": result.evaluated_at},
        {"cost_rule": applicable_cost},
        {"invalidation_rules": ()},
        {
            "invalidation_applicability": InvalidationApplicability.NOT_APPLICABLE,
            "invalidation_not_applicable_reason": "",
        },
        {"invalidation_applicability": object()},
        {"metric_comparisons": ()},
        {"eligible_for_promotion": not result.eligible_for_promotion},
    )
    for mutations in result_cases:
        with pytest.raises(ValueError):
            replace(result, **mutations)


def test_trial_manifest_rejects_future_unavailable_facts() -> None:
    """Evaluation cannot consume an actual fact unavailable at evaluation time."""

    result, _, _, _ = _valid_result()
    future_member = _actual(
        PERIODS[0],
        "profit_margin",
        "11",
        available_at=result.evaluated_at + timedelta(seconds=1),
    )
    future_rows = (replace(result.paired_rows[0], actual=future_member),) + result.paired_rows[1:]
    with pytest.raises(ValueError, match="unavailable at evaluation"):
        replace(
            result,
            paired_rows=future_rows,
            actual_manifest=_actual_manifest(
                future_rows,
                produced_at=result.evaluated_at + timedelta(seconds=2),
            ),
        )


def test_metric_summary_covers_zero_actual_and_all_promotion_reasons() -> None:
    """Metric evaluation must distinguish excluded observations and each failed gate."""

    spec = _spec()
    profit_rule = replace(
        next(item for item in spec.metric_rules if item.metric_code == "profit_margin"),
        mape_zero_actual_rule=MapeZeroActualRule.EXCLUDE_WITH_COVERAGE_PENALTY,
    )
    profit_row = _paired_rows()[0]
    zero_actual = _actual(PERIODS[0], "profit_margin", "0")
    excluded_row = replace(profit_row, actual=zero_actual)
    excluded = _summarize_metric_comparisons(
        expected_period_ends=(PERIODS[0],),
        metric_rules=(profit_rule,),
        metric_evaluation_order=("profit_margin",),
        tie_break_rule=TieBreakRule.BASELINE_WINS,
        rows=(excluded_row,),
    )[0]
    assert excluded.reason_codes == (
        "minimum_sample_count_not_met",
        "minimum_coverage_not_met",
        "minimum_improvement_not_met",
        "baseline_wins_tie",
    )

    revenue_rule = replace(
        next(item for item in spec.metric_rules if item.metric_code == "revenue"),
        maximum_forecast_error=Decimal("0"),
        minimum_improvement=Decimal("1"),
        minimum_sample_count=1,
    )
    revenue_row = _paired_rows()[1]
    adverse_row = replace(
        revenue_row,
        forecast_value=revenue_row.actual.value + Decimal("10"),
        baseline_value=revenue_row.actual.value,
    )
    adverse = _summarize_metric_comparisons(
        expected_period_ends=(PERIODS[0],),
        metric_rules=(revenue_rule,),
        metric_evaluation_order=("revenue",),
        tie_break_rule=TieBreakRule.FORECAST_WINS,
        rows=(adverse_row,),
    )[0]
    assert adverse.reason_codes == (
        "maximum_forecast_error_breached",
        "minimum_improvement_not_met",
    )

    with pytest.raises(ValueError, match="cross-product"):
        _summarize_metric_comparisons(
            expected_period_ends=PERIODS,
            metric_rules=(revenue_rule,),
            metric_evaluation_order=("revenue",),
            tie_break_rule=TieBreakRule.BASELINE_WINS,
            rows=(adverse_row,),
        )


def test_invalidation_zero_actual_rules_and_operators_fail_closed() -> None:
    """Invalidation evaluation must honor zero-actual and exact operator semantics."""

    spec = _spec()
    invalidation = spec.invalidation_rules[0]
    profit_invalidation = replace(invalidation, metric_code="profit_margin")
    zero_row = replace(
        _paired_rows()[0],
        actual=_actual(PERIODS[0], "profit_margin", "0"),
    )
    blocking_rule = next(item for item in spec.metric_rules if item.metric_code == "profit_margin")
    with pytest.raises(ValueError, match="zero-actual"):
        _calculate_invalidation_outcomes(
            invalidation_rules=(profit_invalidation,),
            metric_rules=(blocking_rule,),
            rows=(zero_row,),
        )

    excluding_rule = replace(
        blocking_rule,
        mape_zero_actual_rule=MapeZeroActualRule.EXCLUDE_WITH_COVERAGE_PENALTY,
    )
    outcome = _calculate_invalidation_outcomes(
        invalidation_rules=(profit_invalidation,),
        metric_rules=(excluding_rule,),
        rows=(zero_row,),
    )[0]
    assert outcome.observed_errors == ()

    checks = (
        (InvalidationOperator.GREATER_THAN, Decimal("2"), True),
        (InvalidationOperator.GREATER_THAN_OR_EQUAL, Decimal("3"), True),
        (InvalidationOperator.LESS_THAN, Decimal("4"), True),
        (InvalidationOperator.LESS_THAN_OR_EQUAL, Decimal("3"), True),
    )
    for operator, threshold, expected in checks:
        assert _matches_invalidation(Decimal("3"), operator, threshold) is expected
    with pytest.raises(ValueError, match="unsupported"):
        _matches_invalidation(Decimal("3"), object(), Decimal("3"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="divide by zero"):
        _row_error(Decimal("1"), Decimal("0"), ForecastErrorMetric.MAPE)


def test_evidence_primitives_and_computation_reject_invalid_inputs() -> None:
    """Content-addressed baseline computation must reject unsupported algorithms."""

    computation = _prediction(PERIODS[0], "revenue", "100", 0).computation_evidence
    cases: tuple[dict[str, object], ...] = (
        {"family": object()},
        {"method": object()},
        {"seasonal_lag_periods": 0},
        {
            "family": type(computation.family).EXTERNAL_CONSENSUS,
            "seasonal_lag_periods": 4,
        },
        {"computation_hash": "0" * 64},
    )
    for mutations in cases:
        with pytest.raises(ValueError):
            replace(computation, **mutations)

    member = _pit_input("revenue_actual", "revenue").members[0]
    with pytest.raises(ValueError, match="before effective"):
        replace(member, source_available_at=member.source_effective_at - timedelta(seconds=1))


def test_evidence_scalar_guards_reject_ambiguous_values() -> None:
    """Canonical evidence primitives reject ambiguous scalar representations."""

    with pytest.raises(ValueError, match="bounded token"):
        _require_token("two words", "identity")
    with pytest.raises(ValueError, match="SHA-256"):
        _require_sha256("A" * 64, "content hash")
    with pytest.raises(ValueError, match="timezone-aware"):
        _require_aware(datetime(2026, 1, 1, 9), "observed at")
    with pytest.raises(ValueError, match="finite Decimal"):
        _require_finite(1, "value")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        ForecastCalendarPeriod(period_end=PERIODS[0], ordinal=True)


def test_pit_manifest_schedule_and_horizon_reject_temporal_gaps() -> None:
    """PIT manifests and calendars must remain complete, ordered, and contiguous."""

    pit_input = _pit_input("revenue_actual", "revenue")
    pit_cases: tuple[dict[str, object], ...] = (
        {"manifest_as_of_time": pit_input.manifest_produced_at + timedelta(seconds=1)},
        {"manifest_is_verified": False},
        {"manifest_coverage_ratio": Decimal("0.5")},
        {"manifest_missing_count": 1},
        {"members": ()},
        {"manifest_as_of_time": pit_input.members[0].source_available_at - timedelta(seconds=1)},
        {"selected_versions": ()},
        {"selected_versions_hash": "0" * 64},
    )
    for mutations in pit_cases:
        with pytest.raises(ValueError):
            replace(pit_input, **mutations)

    schedule = _calendar_schedule()
    schedule_cases: tuple[dict[str, object], ...] = (
        {"owner": "equity"},
        {"periods": ()},
        {"content_hash": "0" * 64},
    )
    for mutations in schedule_cases:
        with pytest.raises(ValueError):
            replace(schedule, **mutations)

    horizon = _period_horizon(0)
    horizon_cases: tuple[dict[str, object], ...] = (
        {"target_period_end": horizon.forecast_origin_at.date() - timedelta(days=1)},
        {"horizon_quarters": 0},
        {"origin_period_ordinal": True},
    )
    for mutations in horizon_cases:
        with pytest.raises(ValueError):
            replace(horizon, **mutations)

    with pytest.raises(ValueError, match="not after"):
        ForecastPeriodHorizon.create(
            target_period_end=date(2025, 6, 30),
            forecast_origin_at=datetime(2025, 7, 15, 9, tzinfo=UTC),
            schedule=schedule,
        )
    with pytest.raises(ValueError, match="does not cover"):
        ForecastPeriodHorizon.create(
            target_period_end=PERIODS[0],
            forecast_origin_at=datetime(2020, 1, 1, 9, tzinfo=UTC),
            schedule=schedule,
        )


def test_actual_fact_rejects_revision_and_availability_errors() -> None:
    """Actual evidence must preserve a positive revision and causal availability."""

    actual = _actual(PERIODS[0], "revenue", "105")
    for mutations in (
        {"revision_number": 0},
        {"available_at": actual.effective_at - timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            replace(actual, **mutations)
