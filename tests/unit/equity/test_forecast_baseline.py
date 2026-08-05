"""Unit coverage for the R1 Equity forecast baseline contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.equity.domain.forecast_baseline import (
    ActualFactObservation,
    ActualRevisionRule,
    ActualVintageRule,
    BaselineApprovalStatus,
    BaselineComputationEvidence,
    BaselineComputationMethod,
    BaselineCostRule,
    BaselineFamily,
    BaselineInvalidationRule,
    BaselineMetricRule,
    BaselinePITInputSpec,
    BaselinePITManifestMember,
    BaselinePITSelectedVersion,
    BaselinePredictionObservation,
    CostApplicability,
    EvaluationActualManifest,
    ForecastArtifactReference,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastCalendarPeriod,
    ForecastCalendarScheduleEvidence,
    ForecastErrorMetric,
    ForecastEvaluationPolicy,
    ForecastFreezeRule,
    ForecastPeriodHorizon,
    ForecastScenario,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
    PairedForecastBaselineRow,
    ResearchTrialAuthorization,
    SensitivityArtifactReference,
    TieBreakRule,
)

H = "a" * 64
NOW = datetime(2026, 1, 15, 9, tzinfo=UTC)
PERIODS = (date(2025, 9, 30), date(2025, 12, 31))


def _pit_input(role: str, metric: str) -> BaselinePITInputSpec:
    source_values = ("10", "12") if metric == "profit_margin" else ("100", "110")
    members = tuple(
        BaselinePITManifestMember(
            target_period_end=period,
            source_period_end=date(2024, 9, 30) if index == 0 else date(2024, 12, 31),
            metric_code=metric,
            selected_member_id=f"member:{metric}:{index + 1}",
            selected_member_version=f"member.v{index + 1}",
            selected_member_content_hash=("e" if index == 0 else "f") * 64,
            source_value=Decimal(source_values[index]),
            source_unit="CNY" if metric == "revenue" else "%",
            source_effective_at=datetime(2025, 7, 5, 9, tzinfo=UTC),
            source_available_at=datetime(2025, 7, 10, 9, tzinfo=UTC),
            source_fact_id=f"fact:{metric}:{index + 1}",
            source_fact_version=f"fact.v{index + 1}",
            source_fact_content_hash=("b" if index == 0 else "c") * 64,
            vintage_id=f"vintage:{metric}:{index + 1}",
            vintage_version=f"vintage.v{index + 1}",
            vintage_content_hash=("6" if index == 0 else "7") * 64,
        )
        for index, period in enumerate(PERIODS)
    )
    selected_versions = tuple(
        sorted(
            (
                BaselinePITSelectedVersion(
                    selected_member_id=member.selected_member_id,
                    selected_member_version=member.selected_member_version,
                    selected_member_content_hash=member.selected_member_content_hash,
                    source_fact_id=member.source_fact_id,
                    source_fact_version=member.source_fact_version,
                    source_fact_content_hash=member.source_fact_content_hash,
                    vintage_id=member.vintage_id,
                    vintage_version=member.vintage_version,
                    vintage_content_hash=member.vintage_content_hash,
                )
                for member in members
            ),
            key=lambda item: item.identity_tuple,
        )
    )
    selected_versions_hash = hashlib.sha256(
        json.dumps(
            {
                "schema": "r1-baseline-selected-versions.v1",
                "versions": [list(item.identity_tuple) for item in selected_versions],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return BaselinePITInputSpec(
        input_role=role,
        dataset="research.operating_observation.v1",
        metric_code=metric,
        unit="CNY" if metric == "revenue" else "%",
        pit_manifest_id="pit:r1-baseline:v1",
        pit_manifest_version="manifest.v1",
        pit_manifest_hash="1" * 64,
        manifest_as_of_time=datetime(2025, 7, 10, 9, tzinfo=UTC),
        manifest_produced_at=datetime(2025, 7, 10, 10, tzinfo=UTC),
        manifest_knowledge_scope="public",
        manifest_is_verified=True,
        manifest_coverage_ratio=Decimal("1"),
        manifest_missing_count=0,
        manifest_estimated_count=0,
        manifest_unknown_count=0,
        selected_versions=selected_versions,
        selected_versions_hash=selected_versions_hash,
        members=members,
        calendar_id="calendar:r1-quarterly",
        calendar_version="calendar.v1",
        calendar_content_hash="2" * 64,
    )


def _period_horizon(index: int) -> ForecastPeriodHorizon:
    return ForecastPeriodHorizon.create(
        target_period_end=PERIODS[index],
        forecast_origin_at=datetime(2025, 7, 15, 9, tzinfo=UTC),
        schedule=_calendar_schedule(),
    )


def _calendar_schedule() -> ForecastCalendarScheduleEvidence:
    return ForecastCalendarScheduleEvidence.create(
        owner="data_center",
        calendar_id="calendar:r1-quarterly",
        calendar_version="calendar.v1",
        calendar_content_hash="2" * 64,
        periods=(
            ForecastCalendarPeriod(period_end=date(2025, 6, 30), ordinal=0),
            ForecastCalendarPeriod(period_end=PERIODS[0], ordinal=1),
            ForecastCalendarPeriod(period_end=PERIODS[1], ordinal=2),
        ),
    )


def _evaluation_policy() -> ForecastEvaluationPolicy:
    return ForecastEvaluationPolicy.create(
        policy_id="r1-evaluation-policy:consumer",
        policy_version="policy.v1",
        owner="equity",
        actual_dataset="research.operating-actual.v1",
        actual_knowledge_scope="public",
        actual_revision_rule=ActualRevisionRule.FIRST_PUBLICATION,
        actual_vintage_rule=ActualVintageRule.MANIFEST_AS_OF,
        forecast_freeze_rule=ForecastFreezeRule.PERSISTED_BY_DEADLINE,
        forecast_knowledge_cutoff_at=datetime(2025, 7, 15, 9, tzinfo=UTC),
        forecast_submission_deadline_at=datetime(2025, 7, 16, 9, tzinfo=UTC),
        valid_until=datetime(2027, 1, 1, 9, tzinfo=UTC),
    )


def _spec(
    *,
    zero_rule: MapeZeroActualRule = MapeZeroActualRule.BLOCK,
    minimum_coverage: Decimal = Decimal("1"),
    minimum_sample_count: int = 2,
    tie_break_rule: TieBreakRule = TieBreakRule.BASELINE_WINS,
    approved_at: datetime = datetime(2025, 7, 1, 9, tzinfo=UTC),
    cost_rule: BaselineCostRule | None = None,
    invalidation_threshold: Decimal = Decimal("5"),
    invalidation_applicability: InvalidationApplicability = InvalidationApplicability.APPLICABLE,
    invalidation_rules: tuple[BaselineInvalidationRule, ...] | None = None,
    invalidation_not_applicable_reason: str = "",
) -> ForecastBaselineSpec:
    registered_invalidations = (
        invalidation_rules
        if invalidation_rules is not None
        else (
            BaselineInvalidationRule(
                rule_code="revenue_mae_break",
                metric_code="revenue",
                operator=InvalidationOperator.GREATER_THAN,
                threshold=invalidation_threshold,
                consecutive_periods=2,
            ),
        )
    )
    return ForecastBaselineSpec.create(
        spec_id="r1-baseline-spec:consumer:v1",
        spec_version="baseline-spec.v1",
        owner="equity",
        approval_evidence_id="baseline-approval:consumer:v1",
        approval_evidence_version="approval.v1",
        approval_evidence_content_hash="4" * 64,
        approval_owner="equity",
        approval_status=BaselineApprovalStatus.APPROVED,
        evaluation_policy=_evaluation_policy(),
        subject_code="600519.SH",
        industry_code="consumer-staples",
        candidate_scenario=ForecastScenario.BASE,
        horizon_quarters=2,
        family=BaselineFamily.SEASONAL_NAIVE,
        computation_method=BaselineComputationMethod.DIRECT_APPROVED_SOURCE,
        computation_code_version="equity.baseline.direct.v1",
        family_parameter_version="seasonal-params.v1",
        family_parameter_hash=H,
        seasonal_lag_periods=4,
        pit_inputs=(
            _pit_input("profit_margin_actual", "profit_margin"),
            _pit_input("revenue_actual", "revenue"),
        ),
        training_window_start=date(2023, 1, 1),
        training_window_end=date(2025, 6, 30),
        expected_period_ends=PERIODS,
        calendar_schedule=_calendar_schedule(),
        period_horizons=(_period_horizon(0), _period_horizon(1)),
        metric_rules=(
            BaselineMetricRule(
                metric_code="revenue",
                error_metric=ForecastErrorMetric.MAE,
                maximum_forecast_error=Decimal("3"),
                minimum_improvement=Decimal("0.5"),
                minimum_sample_count=minimum_sample_count,
                minimum_coverage=minimum_coverage,
                mape_zero_actual_rule=MapeZeroActualRule.BLOCK,
            ),
            BaselineMetricRule(
                metric_code="profit_margin",
                error_metric=ForecastErrorMetric.MAPE,
                maximum_forecast_error=Decimal("0.2"),
                minimum_improvement=Decimal("0.01"),
                minimum_sample_count=minimum_sample_count,
                minimum_coverage=minimum_coverage,
                mape_zero_actual_rule=zero_rule,
            ),
        ),
        metric_evaluation_order=("revenue", "profit_margin"),
        tie_break_rule=tie_break_rule,
        cost_rule=cost_rule
        or BaselineCostRule(
            applicability=CostApplicability.NOT_APPLICABLE,
            cost_model_version="",
            cost_model_content_hash="",
            not_applicable_reason="Operating forecast accuracy has no trading-cost adjustment.",
        ),
        invalidation_applicability=invalidation_applicability,
        invalidation_rules=registered_invalidations,
        invalidation_not_applicable_reason=invalidation_not_applicable_reason,
        approved_at=approved_at,
        approval_recorded_at=approved_at,
        valid_until=datetime(2027, 1, 1, 9, tzinfo=UTC),
    )


def _forecast(index: int, *, tie: bool = False) -> ForecastArtifactReference:
    period_horizon = _period_horizon(index)
    as_of = period_horizon.forecast_origin_at
    projected = (
        (("profit_margin", Decimal("10")), ("revenue", Decimal("100")))
        if index == 0 and tie
        else (
            (("profit_margin", Decimal("12")), ("revenue", Decimal("110")))
            if tie
            else (
                (("profit_margin", Decimal("11")), ("revenue", Decimal("104")))
                if index == 0
                else (("profit_margin", Decimal("11")), ("revenue", Decimal("111")))
            )
        )
    )
    return ForecastArtifactReference(
        forecast_id=f"forecast:r1:{index + 1}",
        forecast_version=index + 1,
        forecast_content_hash=str(index + 3) * 64,
        subject_code="600519.SH",
        industry_code="consumer-staples",
        candidate_scenario=ForecastScenario.BASE,
        horizon_quarters=period_horizon.horizon_quarters,
        period_horizon=period_horizon,
        metric_values=projected,
        metric_units=(("profit_margin", "%"), ("revenue", "CNY")),
        as_of_time=as_of,
        persisted_at=as_of + timedelta(hours=1),
        target_period_end=PERIODS[index],
        template_owner="sector",
        template_code="consumer-template",
        template_version=1,
        template_content_hash="5" * 64,
        template_run_owner="sector",
        template_run_key=f"template-run:r1:{index + 1}",
        template_run_version=1,
        template_run_content_hash=str(index + 6) * 64,
        sensitivity_artifacts=(
            SensitivityArtifactReference(
                owner="valuation",
                artifact_id=f"sensitivity:r1:{index + 1}",
                artifact_version="sensitivity.v1",
                artifact_content_hash=str(index + 8) * 64,
            ),
        ),
    )


def _prediction(
    period: date,
    metric: str,
    value: str,
    forecast_index: int,
) -> BaselinePredictionObservation:
    pit_input = _pit_input(f"{metric}_actual", metric)
    member = pit_input.members[forecast_index]
    computation = BaselineComputationEvidence.create(
        family=BaselineFamily.SEASONAL_NAIVE,
        method=BaselineComputationMethod.DIRECT_APPROVED_SOURCE,
        code_version="equity.baseline.direct.v1",
        family_parameter_version="seasonal-params.v1",
        family_parameter_hash=H,
        seasonal_lag_periods=4,
        source_value=member.source_value,
        source_unit=member.source_unit,
        source_member_id=member.selected_member_id,
        source_member_version=member.selected_member_version,
        source_member_content_hash=member.selected_member_content_hash,
        source_fact_id=member.source_fact_id,
        source_fact_version=member.source_fact_version,
        source_fact_content_hash=member.source_fact_content_hash,
        source_vintage_id=member.vintage_id,
        source_vintage_version=member.vintage_version,
        source_vintage_content_hash=member.vintage_content_hash,
    )
    return BaselinePredictionObservation(
        period_end=period,
        metric_code=metric,
        input_role=f"{metric}_actual",
        value=Decimal(value),
        unit="CNY" if metric == "revenue" else "%",
        pit_manifest_id="pit:r1-baseline:v1",
        pit_manifest_hash="1" * 64,
        selected_member_id=member.selected_member_id,
        selected_member_version=member.selected_member_version,
        selected_member_content_hash=member.selected_member_content_hash,
        source_fact_id=member.source_fact_id,
        source_fact_version=member.source_fact_version,
        source_fact_content_hash=member.source_fact_content_hash,
        computation_evidence=computation,
        effective_at=member.source_effective_at,
        available_at=member.source_available_at,
        vintage_id=member.vintage_id,
        vintage_version=member.vintage_version,
        vintage_content_hash=member.vintage_content_hash,
    )


def _artifact(
    spec: ForecastBaselineSpec,
    *,
    tie: bool = False,
    forecasts: tuple[ForecastArtifactReference, ...] | None = None,
) -> ForecastBaselineArtifact:
    return ForecastBaselineArtifact.create(
        artifact_id="r1-baseline-artifact:consumer:v1",
        artifact_version="baseline-artifact.v1",
        owner="equity",
        spec=spec,
        forecasts=forecasts or (_forecast(0, tie=tie), _forecast(1, tie=tie)),
        predictions=(
            _prediction(PERIODS[0], "profit_margin", "10", 0),
            _prediction(PERIODS[0], "revenue", "100", 0),
            _prediction(PERIODS[1], "profit_margin", "12", 1),
            _prediction(PERIODS[1], "revenue", "110", 1),
        ),
        knowledge_as_of=datetime(2026, 1, 10, 9, tzinfo=UTC),
        produced_at=datetime(2026, 1, 10, 9, tzinfo=UTC),
        valid_until=datetime(2026, 12, 31, 9, tzinfo=UTC),
    )


def _actual(
    period: date,
    metric: str,
    value: str,
    *,
    unit: str | None = None,
    subject_code: str = "600519.SH",
    industry_code: str = "consumer-staples",
    pit_manifest_id: str = "pit:r1-evaluation-actuals:v1",
    pit_manifest_hash: str = "6" * 64,
    upstream_fact_content_hash: str = "c" * 64,
    available_at: datetime = NOW - timedelta(days=2),
) -> ActualFactObservation:
    digest_char = {
        (PERIODS[0], "profit_margin"): "7",
        (PERIODS[0], "revenue"): "8",
        (PERIODS[1], "profit_margin"): "9",
        (PERIODS[1], "revenue"): "a",
    }[(period, metric)]
    return ActualFactObservation.create(
        subject_code=subject_code,
        industry_code=industry_code,
        dataset="research.operating-actual.v1",
        period_end=period,
        metric_code=metric,
        value=Decimal(value),
        unit=unit or ("CNY" if metric == "revenue" else "%"),
        source_fact_id=f"actual:{period}:{metric}",
        source_fact_version="actual.v1",
        source_fact_content_hash=upstream_fact_content_hash,
        revision_number=1,
        effective_at=datetime.combine(period, datetime.min.time(), UTC),
        available_at=available_at,
        vintage_id=f"actual-vintage:{period}:{metric}",
        vintage_version="vintage.v1",
        vintage_content_hash="d" * 64,
        pit_manifest_id=pit_manifest_id,
        pit_manifest_hash=pit_manifest_hash,
        manifest_member_id=f"actual-member:{period}:{metric}",
        manifest_member_version="member.v1",
        manifest_member_content_hash=digest_char * 64,
        calendar_id="calendar:r1-quarterly",
        calendar_version="calendar.v1",
        calendar_content_hash="2" * 64,
    )


def _actual_manifest(
    rows: tuple[PairedForecastBaselineRow, ...],
    *,
    produced_at: datetime = NOW - timedelta(days=1),
) -> EvaluationActualManifest:
    members = tuple(item.actual for item in rows)
    selected_versions = tuple(
        sorted(
            (
                BaselinePITSelectedVersion(
                    selected_member_id=item.manifest_member_id,
                    selected_member_version=item.manifest_member_version,
                    selected_member_content_hash=item.manifest_member_content_hash,
                    source_fact_id=item.source_fact_id,
                    source_fact_version=item.source_fact_version,
                    source_fact_content_hash=item.source_fact_content_hash,
                    vintage_id=item.vintage_id,
                    vintage_version=item.vintage_version,
                    vintage_content_hash=item.vintage_content_hash,
                )
                for item in members
            ),
            key=lambda item: item.identity_tuple,
        )
    )
    selected_versions_hash = hashlib.sha256(
        json.dumps(
            {
                "schema": "r1-actual-selected-versions.v1",
                "versions": [list(item.identity_tuple) for item in selected_versions],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return EvaluationActualManifest.create(
        manifest_id="pit:r1-evaluation-actuals:v1",
        manifest_version="evaluation-actuals.v1",
        manifest_content_hash="6" * 64,
        owner="data_center",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        dataset="research.operating-actual.v1",
        calendar_id="calendar:r1-quarterly",
        calendar_version="calendar.v1",
        calendar_content_hash="2" * 64,
        as_of_time=produced_at,
        produced_at=produced_at,
        knowledge_scope="public",
        is_verified=True,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        selected_versions=selected_versions,
        selected_versions_hash=selected_versions_hash,
        members=members,
    )


def _paired_rows(
    *,
    second_margin_actual: str = "10",
    tie: bool = False,
) -> tuple[PairedForecastBaselineRow, ...]:
    values = (
        (PERIODS[0], "profit_margin", "11", "10", "11", 0),
        (PERIODS[0], "revenue", "104", "100", "105", 0),
        (PERIODS[1], "profit_margin", "11", "12", second_margin_actual, 1),
        (PERIODS[1], "revenue", "111", "110", "112", 1),
    )
    return tuple(
        PairedForecastBaselineRow(
            period_end=period,
            metric_code=metric,
            forecast_id=_forecast(index, tie=tie).forecast_id,
            forecast_content_hash=_forecast(index, tie=tie).forecast_content_hash,
            forecast_value=Decimal(baseline if tie else forecast),
            baseline_value=Decimal(baseline),
            actual=_actual(period, metric, actual),
        )
        for period, metric, forecast, baseline, actual, index in values
    )


def _result(
    spec: ForecastBaselineSpec,
    artifact: ForecastBaselineArtifact,
    rows: tuple[PairedForecastBaselineRow, ...],
    *,
    actual_manifest: EvaluationActualManifest | None = None,
    evaluated_at: datetime = NOW,
    valid_until: datetime = datetime(2026, 12, 31, 9, tzinfo=UTC),
) -> ForecastBaselineTrialResult:
    research_trial = ResearchTrialAuthorization(
        trial_id="research-trial:r1:v1",
        trial_version="research-trial.v1",
        trial_content_hash="e" * 64,
        owner="research",
        capability="r1",
        purpose="valuation",
        status="running",
        split_spec_hash="f" * 64,
        parameter_hash="1" * 64,
        baseline_spec_id=spec.spec_id,
        baseline_spec_version=spec.spec_version,
        baseline_spec_content_hash=spec.content_hash,
        expected_period_ends=spec.expected_period_ends,
        metric_codes=tuple(item.metric_code for item in spec.metric_rules),
        calendar_schedule_hash=spec.calendar_schedule.content_hash,
        evaluation_policy=spec.evaluation_policy,
        baseline_spec_approved_at=spec.approved_at,
        forecast_origin_at=artifact.forecasts[0].as_of_time,
        activated_at=spec.approved_at,
        recorded_at=spec.approved_at,
        valid_until=spec.valid_until,
    )
    return ForecastBaselineTrialResult.create(
        result_id="r1-trial-result:consumer:v1",
        result_version="trial-result.v1",
        owner="equity",
        research_trial=research_trial,
        spec=spec,
        artifact=artifact,
        paired_rows=rows,
        actual_manifest=actual_manifest or _actual_manifest(rows),
        evaluated_at=evaluated_at,
        valid_until=valid_until,
    )


def test_approved_spec_artifact_and_paired_trial_are_exact_and_eligible() -> None:
    spec = _spec()
    artifact = _artifact(spec)
    result = _result(spec, artifact, _paired_rows())

    assert result.eligible_for_promotion is True
    assert tuple(item.metric_code for item in result.metric_comparisons) == (
        "revenue",
        "profit_margin",
    )
    assert all(item.coverage == 1 for item in result.metric_comparisons)
    assert (
        artifact.predictions[0].selected_member_version
        != artifact.predictions[2].selected_member_version
    )
    assert result.actual_manifest.manifest_id != spec.pit_inputs[0].pit_manifest_id
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True


def test_cross_product_and_available_at_leakage_fail_closed() -> None:
    spec = _spec()
    artifact = _artifact(spec)
    with pytest.raises(ValueError, match="full period-metric cross-product"):
        _result(spec, artifact, _paired_rows()[:-1])

    leaked = replace(
        _paired_rows()[0],
        actual=_actual(
            PERIODS[0],
            "profit_margin",
            "11",
            available_at=NOW + timedelta(minutes=1),
        ),
    )
    with pytest.raises(ValueError, match="actual manifest"):
        _result(spec, artifact, (leaked, *_paired_rows()[1:]))

    future_baseline = replace(
        artifact.predictions[0],
        available_at=artifact.forecasts[0].as_of_time + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="not a selected PIT member"):
        replace(
            artifact,
            predictions=(future_baseline, *artifact.predictions[1:]),
            content_hash=artifact.content_hash,
        )


def test_mape_zero_rule_coverage_and_tie_break_are_explicit() -> None:
    excluding_spec = _spec(
        zero_rule=MapeZeroActualRule.EXCLUDE_WITH_COVERAGE_PENALTY,
        minimum_coverage=Decimal("0.5"),
        minimum_sample_count=1,
    )
    excluding = _result(
        excluding_spec,
        _artifact(excluding_spec),
        _paired_rows(second_margin_actual="0"),
    )
    margin = next(
        item for item in excluding.metric_comparisons if item.metric_code == "profit_margin"
    )
    assert margin.coverage == Decimal("0.5")

    blocking_spec = _spec(zero_rule=MapeZeroActualRule.BLOCK)
    with pytest.raises(ValueError, match="zero-actual rule blocks"):
        _result(
            blocking_spec,
            _artifact(blocking_spec),
            _paired_rows(second_margin_actual="0"),
        )

    tie_spec = _spec(
        minimum_coverage=Decimal("1"),
        minimum_sample_count=2,
        tie_break_rule=TieBreakRule.BASELINE_WINS,
    )
    tied = _result(tie_spec, _artifact(tie_spec, tie=True), _paired_rows(tie=True))
    assert tied.eligible_for_promotion is False
    assert all("baseline_wins_tie" in item.reason_codes for item in tied.metric_comparisons)


def test_paired_forecast_value_must_match_typed_forecast_reference() -> None:
    spec = _spec()
    artifact = _artifact(spec)
    changed = replace(_paired_rows()[0], forecast_value=Decimal("11.01"))

    with pytest.raises(ValueError, match="forecast/baseline/PIT evidence"):
        _result(spec, artifact, (changed, *_paired_rows()[1:]))


def test_forecast_created_before_spec_approval_is_rejected() -> None:
    with pytest.raises(ValueError, match="submission deadline"):
        _spec(approved_at=datetime(2025, 8, 1, 9, tzinfo=UTC))


def test_trial_at_exact_upstream_expiry_is_rejected() -> None:
    spec = _spec()
    artifact = _artifact(spec)

    with pytest.raises(ValueError, match="outside an active upstream window"):
        _result(
            spec,
            artifact,
            _paired_rows(),
            evaluated_at=artifact.valid_until,
            valid_until=spec.valid_until,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("subject_code", "000001.SZ"),
        ("candidate_scenario", ForecastScenario.BEAR),
    ),
)
def test_forecast_scope_and_scenario_must_match_spec(
    field_name: str,
    value: object,
) -> None:
    spec = _spec()
    mismatched = replace(_forecast(0), **{field_name: value})

    with pytest.raises(ValueError, match="scope does not match"):
        _artifact(spec, forecasts=(mismatched, _forecast(1)))


def test_forecast_scenario_requires_existing_typed_enum() -> None:
    with pytest.raises(ValueError, match="must be a ForecastScenario"):
        replace(_forecast(0), candidate_scenario="base")


def test_forecast_period_horizon_must_match_registered_mapping() -> None:
    spec = _spec()
    wrong_horizon = replace(_period_horizon(0), horizon_quarters=2)
    mismatched = replace(
        _forecast(0),
        horizon_quarters=2,
        period_horizon=wrong_horizon,
    )

    with pytest.raises(ValueError, match="period horizon does not match"):
        _artifact(spec, forecasts=(mismatched, _forecast(1)))


def test_prediction_source_must_be_selected_manifest_member() -> None:
    spec = _spec()
    artifact = _artifact(spec)
    first = artifact.predictions[0]
    fake_evidence = BaselineComputationEvidence.create(
        family=first.computation_evidence.family,
        method=first.computation_evidence.method,
        code_version=first.computation_evidence.code_version,
        family_parameter_version=first.computation_evidence.family_parameter_version,
        family_parameter_hash=first.computation_evidence.family_parameter_hash,
        seasonal_lag_periods=first.computation_evidence.seasonal_lag_periods,
        source_value=first.value,
        source_unit=first.unit,
        source_member_id="member:not-in-manifest",
        source_member_version="member.v999",
        source_member_content_hash="f" * 64,
        source_fact_id="fact:not-in-manifest",
        source_fact_version="fact.v999",
        source_fact_content_hash="f" * 64,
        source_vintage_id="vintage:not-in-manifest",
        source_vintage_version="vintage.v999",
        source_vintage_content_hash="f" * 64,
    )
    non_member = replace(
        first,
        selected_member_id="member:not-in-manifest",
        selected_member_version="member.v999",
        selected_member_content_hash="f" * 64,
        source_fact_id="fact:not-in-manifest",
        source_fact_version="fact.v999",
        source_fact_content_hash="f" * 64,
        vintage_id="vintage:not-in-manifest",
        vintage_version="vintage.v999",
        vintage_content_hash="f" * 64,
        computation_evidence=fake_evidence,
    )

    with pytest.raises(ValueError, match="not a selected PIT member"):
        replace(
            artifact,
            predictions=(non_member, *artifact.predictions[1:]),
            content_hash=artifact.content_hash,
        )


def test_prediction_cannot_reuse_another_target_period_member() -> None:
    spec = _spec()
    artifact = _artifact(spec)
    first = artifact.predictions[0]
    second_period_member = spec.pit_inputs[0].members[1]
    wrong_evidence = BaselineComputationEvidence.create(
        family=first.computation_evidence.family,
        method=first.computation_evidence.method,
        code_version=first.computation_evidence.code_version,
        family_parameter_version=first.computation_evidence.family_parameter_version,
        family_parameter_hash=first.computation_evidence.family_parameter_hash,
        seasonal_lag_periods=first.computation_evidence.seasonal_lag_periods,
        source_value=second_period_member.source_value,
        source_unit=second_period_member.source_unit,
        source_member_id=second_period_member.selected_member_id,
        source_member_version=second_period_member.selected_member_version,
        source_member_content_hash=second_period_member.selected_member_content_hash,
        source_fact_id=second_period_member.source_fact_id,
        source_fact_version=second_period_member.source_fact_version,
        source_fact_content_hash=second_period_member.source_fact_content_hash,
        source_vintage_id=second_period_member.vintage_id,
        source_vintage_version=second_period_member.vintage_version,
        source_vintage_content_hash=second_period_member.vintage_content_hash,
    )
    wrong_period = replace(
        first,
        value=second_period_member.source_value,
        selected_member_id=second_period_member.selected_member_id,
        selected_member_version=second_period_member.selected_member_version,
        selected_member_content_hash=second_period_member.selected_member_content_hash,
        source_fact_id=second_period_member.source_fact_id,
        source_fact_version=second_period_member.source_fact_version,
        source_fact_content_hash=second_period_member.source_fact_content_hash,
        vintage_id=second_period_member.vintage_id,
        vintage_version=second_period_member.vintage_version,
        vintage_content_hash=second_period_member.vintage_content_hash,
        computation_evidence=wrong_evidence,
    )

    with pytest.raises(ValueError, match="not a selected PIT member"):
        replace(
            artifact,
            predictions=(wrong_period, *artifact.predictions[1:]),
            content_hash=artifact.content_hash,
        )


def test_applicable_cost_without_executed_evidence_fails_closed() -> None:
    applicable = BaselineCostRule(
        applicability=CostApplicability.APPLICABLE,
        cost_model_version="cost-model.v1",
        cost_model_content_hash="9" * 64,
        not_applicable_reason="",
    )
    spec = _spec(cost_rule=applicable)

    with pytest.raises(ValueError, match="requires executed cost evidence"):
        _artifact(spec)


def test_invalidation_outcome_triggers_and_blocks_eligibility() -> None:
    triggered_spec = _spec(invalidation_threshold=Decimal("0.5"))
    result = _result(triggered_spec, _artifact(triggered_spec), _paired_rows())

    assert result.eligible_for_promotion is False
    assert result.invalidation_outcomes[0].triggered_at == PERIODS[1]
    assert result.invalidation_outcomes[0].reason_codes == (
        "invalidation_rule_triggered:revenue_mae_break",
    )


def test_invalidation_outcome_remains_clear_when_sequence_does_not_match() -> None:
    result = _result(_spec(), _artifact(_spec()), _paired_rows())

    assert result.eligible_for_promotion is True
    assert result.invalidation_outcomes[0].triggered_at is None
    assert result.invalidation_outcomes[0].passes is True


def test_tampered_invalidation_outcome_is_recomputed_and_rejected() -> None:
    spec = _spec()
    result = _result(spec, _artifact(spec), _paired_rows())
    outcome = result.invalidation_outcomes[0]
    tampered = replace(
        outcome,
        triggered_at=PERIODS[1],
        passes=False,
        reason_codes=("invalidation_rule_triggered:revenue_mae_break",),
    )

    with pytest.raises(ValueError, match="outcomes do not match paired rows"):
        replace(result, invalidation_outcomes=(tampered,))


def test_actual_value_tamper_breaks_exact_fact_hash() -> None:
    actual = _paired_rows()[0].actual

    with pytest.raises(ValueError, match="actual observation hash mismatch"):
        replace(actual, value=actual.value + Decimal("1"))


def test_actual_unit_must_match_forecast_and_baseline_evidence() -> None:
    spec = _spec()
    rows = _paired_rows()
    actual = _actual(PERIODS[0], "profit_margin", "11", unit="bps")
    mismatched = replace(rows[0], actual=actual)

    with pytest.raises(ValueError, match="forecast/baseline/PIT evidence"):
        _result(spec, _artifact(spec), (mismatched, *rows[1:]))


@pytest.mark.parametrize(
    "actual",
    (
        _actual(
            PERIODS[0],
            "profit_margin",
            "11",
            pit_manifest_id="pit:not-this-manifest:v1",
        ),
        _actual(
            PERIODS[0],
            "profit_margin",
            "11",
            subject_code="000001.SZ",
        ),
    ),
)
def test_actual_manifest_rejects_inconsistent_member_identity(
    actual: ActualFactObservation,
) -> None:
    rows = _paired_rows()
    mismatched = replace(rows[0], actual=actual)

    with pytest.raises(ValueError, match="member identity is inconsistent"):
        _actual_manifest((mismatched, *rows[1:]))


def test_actual_manifest_accepts_member_available_at_exact_production_time() -> None:
    rows = _paired_rows()
    manifest = _actual_manifest(rows, produced_at=NOW - timedelta(days=2))

    result = _result(_spec(), _artifact(_spec()), rows, actual_manifest=manifest)

    assert result.actual_manifest.manifest_id == "pit:r1-evaluation-actuals:v1"


def test_actual_manifest_rejects_member_published_after_manifest_production() -> None:
    rows = _paired_rows()
    later_actual = _actual(
        PERIODS[0],
        "profit_margin",
        "11",
        available_at=NOW - timedelta(hours=12),
    )
    changed = (replace(rows[0], actual=later_actual), *rows[1:])

    with pytest.raises(ValueError, match="unavailable"):
        _actual_manifest(changed, produced_at=NOW - timedelta(days=1))


def test_actual_manifest_rejects_one_identity_reused_for_distinct_keys() -> None:
    rows = _paired_rows()
    original = rows[0].actual
    target = rows[1].actual
    duplicated_identity = ActualFactObservation.create(
        subject_code=target.subject_code,
        industry_code=target.industry_code,
        dataset=target.dataset,
        period_end=target.period_end,
        metric_code=target.metric_code,
        value=target.value,
        unit=target.unit,
        source_fact_id=original.source_fact_id,
        source_fact_version=original.source_fact_version,
        source_fact_content_hash=original.source_fact_content_hash,
        revision_number=target.revision_number,
        effective_at=target.effective_at,
        available_at=target.available_at,
        vintage_id=original.vintage_id,
        vintage_version=original.vintage_version,
        vintage_content_hash=original.vintage_content_hash,
        pit_manifest_id=target.pit_manifest_id,
        pit_manifest_hash=target.pit_manifest_hash,
        manifest_member_id=original.manifest_member_id,
        manifest_member_version=original.manifest_member_version,
        manifest_member_content_hash=original.manifest_member_content_hash,
        calendar_id=target.calendar_id,
        calendar_version=target.calendar_version,
        calendar_content_hash=target.calendar_content_hash,
    )
    changed = (rows[0], replace(rows[1], actual=duplicated_identity), *rows[2:])

    with pytest.raises(ValueError, match="globally unique"):
        _actual_manifest(changed)


def test_future_actual_manifest_is_unavailable_at_evaluation() -> None:
    rows = _paired_rows()
    manifest = _actual_manifest(rows, produced_at=NOW + timedelta(minutes=1))

    with pytest.raises(ValueError, match="unavailable at evaluation time"):
        _result(_spec(), _artifact(_spec()), rows, actual_manifest=manifest)


def test_self_consistent_actual_wrapper_cannot_replace_manifest_upstream_fact() -> None:
    rows = _paired_rows()
    original_manifest = _actual_manifest(rows)
    forged_actual = _actual(
        PERIODS[0],
        "profit_margin",
        "11",
        upstream_fact_content_hash="f" * 64,
    )
    forged_rows = (replace(rows[0], actual=forged_actual), *rows[1:])

    with pytest.raises(ValueError, match="exactly match actual manifest members"):
        _result(
            _spec(),
            _artifact(_spec()),
            forged_rows,
            actual_manifest=original_manifest,
        )


def test_baseline_prediction_value_cannot_diverge_from_computation_evidence() -> None:
    prediction = _artifact(_spec()).predictions[0]

    with pytest.raises(ValueError, match="does not match computation evidence"):
        replace(prediction, value=Decimal("0"))


@pytest.mark.parametrize(
    "mismatch",
    ("family", "params", "code", "source_value", "unit", "member"),
)
def test_baseline_computation_evidence_must_match_approved_source(
    mismatch: str,
) -> None:
    spec = _spec()
    artifact = _artifact(spec)
    prediction = artifact.predictions[0]
    evidence = prediction.computation_evidence
    family = BaselineFamily.EXTERNAL_CONSENSUS if mismatch == "family" else evidence.family
    seasonal_lag_periods = None if mismatch == "family" else evidence.seasonal_lag_periods
    code_version = "wrong.code.v2" if mismatch == "code" else evidence.code_version
    parameter_hash = "d" * 64 if mismatch == "params" else evidence.family_parameter_hash
    source_value = Decimal("999") if mismatch == "source_value" else evidence.source_value
    source_unit = "bps" if mismatch == "unit" else evidence.source_unit
    member_id = "member:not-approved" if mismatch == "member" else evidence.source_member_id
    member_version = "member.v999" if mismatch == "member" else evidence.source_member_version
    member_hash = "d" * 64 if mismatch == "member" else evidence.source_member_content_hash
    changed_evidence = BaselineComputationEvidence.create(
        family=family,
        method=evidence.method,
        code_version=code_version,
        family_parameter_version=evidence.family_parameter_version,
        family_parameter_hash=parameter_hash,
        seasonal_lag_periods=seasonal_lag_periods,
        source_value=source_value,
        source_unit=source_unit,
        source_member_id=member_id,
        source_member_version=member_version,
        source_member_content_hash=member_hash,
        source_fact_id=evidence.source_fact_id,
        source_fact_version=evidence.source_fact_version,
        source_fact_content_hash=evidence.source_fact_content_hash,
        source_vintage_id=evidence.source_vintage_id,
        source_vintage_version=evidence.source_vintage_version,
        source_vintage_content_hash=evidence.source_vintage_content_hash,
    )
    changed = replace(
        prediction,
        value=source_value,
        unit=source_unit,
        selected_member_id=member_id,
        selected_member_version=member_version,
        selected_member_content_hash=member_hash,
        computation_evidence=changed_evidence,
    )

    with pytest.raises(ValueError, match="not a selected PIT member"):
        replace(
            artifact,
            predictions=(changed, *artifact.predictions[1:]),
            content_hash=artifact.content_hash,
        )


def test_baseline_computation_hash_is_decimal_scale_canonical() -> None:
    evidence = _artifact(_spec()).predictions[0].computation_evidence
    scaled = BaselineComputationEvidence.create(
        family=evidence.family,
        method=evidence.method,
        code_version=evidence.code_version,
        family_parameter_version=evidence.family_parameter_version,
        family_parameter_hash=evidence.family_parameter_hash,
        seasonal_lag_periods=evidence.seasonal_lag_periods,
        source_value=Decimal("10.000"),
        source_unit=evidence.source_unit,
        source_member_id=evidence.source_member_id,
        source_member_version=evidence.source_member_version,
        source_member_content_hash=evidence.source_member_content_hash,
        source_fact_id=evidence.source_fact_id,
        source_fact_version=evidence.source_fact_version,
        source_fact_content_hash=evidence.source_fact_content_hash,
        source_vintage_id=evidence.source_vintage_id,
        source_vintage_version=evidence.source_vintage_version,
        source_vintage_content_hash=evidence.source_vintage_content_hash,
    )

    assert scaled.computation_hash == evidence.computation_hash


def test_empty_applicable_invalidation_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires non-empty rules"):
        _spec(invalidation_rules=())


def test_explicit_non_applicable_invalidation_requires_owner_rationale() -> None:
    with pytest.raises(ValueError, match="non-blank text"):
        _spec(
            invalidation_applicability=InvalidationApplicability.NOT_APPLICABLE,
            invalidation_rules=(),
            invalidation_not_applicable_reason="",
        )

    spec = _spec(
        invalidation_applicability=InvalidationApplicability.NOT_APPLICABLE,
        invalidation_rules=(),
        invalidation_not_applicable_reason="Owner confirms no invalidation condition applies.",
    )
    result = _result(spec, _artifact(spec), _paired_rows())
    assert result.invalidation_outcomes == ()
    assert result.eligible_for_promotion is True


def test_synchronized_self_reported_horizon_is_rejected_by_calendar_schedule() -> None:
    spec = _spec()
    forged_horizon = replace(spec.period_horizons[0], horizon_quarters=2)
    forged_reference = replace(
        _forecast(0),
        horizon_quarters=2,
        period_horizon=forged_horizon,
    )
    assert forged_reference.horizon_quarters == 2

    with pytest.raises(ValueError, match="derived from the calendar schedule"):
        replace(
            spec,
            period_horizons=(forged_horizon, spec.period_horizons[1]),
            content_hash=spec.content_hash,
        )


def test_hashes_are_decimal_scale_and_timezone_independent_and_tamper_evident() -> None:
    canonical = _spec()
    offset = timezone(timedelta(hours=8))
    scaled = _spec(approved_at=canonical.approved_at.astimezone(offset))
    scaled_rule = replace(
        scaled.metric_rules[0],
        maximum_forecast_error=Decimal("0.200"),
        minimum_improvement=Decimal("0.010"),
        minimum_coverage=Decimal("1.0"),
    )
    scaled = ForecastBaselineSpec.create(
        spec_id=scaled.spec_id,
        spec_version=scaled.spec_version,
        owner=scaled.owner,
        approval_evidence_id=scaled.approval_evidence_id,
        approval_evidence_version=scaled.approval_evidence_version,
        approval_evidence_content_hash=scaled.approval_evidence_content_hash,
        approval_owner=scaled.approval_owner,
        approval_status=scaled.approval_status,
        evaluation_policy=scaled.evaluation_policy,
        subject_code=scaled.subject_code,
        industry_code=scaled.industry_code,
        candidate_scenario=scaled.candidate_scenario,
        horizon_quarters=scaled.horizon_quarters,
        family=scaled.family,
        computation_method=scaled.computation_method,
        computation_code_version=scaled.computation_code_version,
        family_parameter_version=scaled.family_parameter_version,
        family_parameter_hash=scaled.family_parameter_hash,
        seasonal_lag_periods=scaled.seasonal_lag_periods,
        pit_inputs=scaled.pit_inputs,
        training_window_start=scaled.training_window_start,
        training_window_end=scaled.training_window_end,
        expected_period_ends=scaled.expected_period_ends,
        calendar_schedule=scaled.calendar_schedule,
        period_horizons=scaled.period_horizons,
        metric_rules=(scaled_rule, scaled.metric_rules[1]),
        metric_evaluation_order=scaled.metric_evaluation_order,
        tie_break_rule=scaled.tie_break_rule,
        cost_rule=scaled.cost_rule,
        invalidation_applicability=scaled.invalidation_applicability,
        invalidation_rules=scaled.invalidation_rules,
        invalidation_not_applicable_reason=scaled.invalidation_not_applicable_reason,
        approved_at=scaled.approved_at,
        approval_recorded_at=scaled.approval_recorded_at.astimezone(offset),
        valid_until=scaled.valid_until.astimezone(offset),
    )
    assert canonical.content_hash == scaled.content_hash

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(canonical, content_hash="0" * 64)
    with pytest.raises(ValueError, match="must remain research-only"):
        replace(canonical, must_not_use_for_decision=False)


def test_evaluation_policy_hash_and_public_scope_are_tamper_evident() -> None:
    policy = _evaluation_policy()
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(policy, actual_dataset="research.other-actual.v1")
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(
            policy,
            forecast_submission_deadline_at=(
                policy.forecast_submission_deadline_at + timedelta(minutes=1)
            ),
        )
    with pytest.raises(ValueError, match="unsupported"):
        replace(policy, actual_knowledge_scope="system")
    with pytest.raises(ValueError, match="public knowledge"):
        replace(_pit_input("revenue_actual", "revenue"), manifest_knowledge_scope="system")


def test_trial_hash_seals_complete_forecast_reference() -> None:
    spec = _spec()
    result = _result(spec, _artifact(spec), _paired_rows())
    forecast = result.forecasts[0]
    changed_run = replace(forecast, template_run_key="template-run:substituted")
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(
            result,
            forecasts=(changed_run, *result.forecasts[1:]),
            content_hash=result.content_hash,
        )

    sensitivity = forecast.sensitivity_artifacts[0]
    changed_sensitivity = replace(sensitivity, artifact_id="sensitivity:substituted")
    changed_forecast = replace(
        forecast,
        sensitivity_artifacts=(changed_sensitivity,),
    )
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(
            result,
            forecasts=(changed_forecast, *result.forecasts[1:]),
            content_hash=result.content_hash,
        )
