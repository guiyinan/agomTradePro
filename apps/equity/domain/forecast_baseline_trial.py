"""R1 paired forecast comparison, invalidation and promotion-gate contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .forecast_baseline_authority import (
    EvaluationActualManifest,
    ResearchTrialAuthorization,
)
from .forecast_baseline_contracts import (
    BaselineCostRule,
    BaselineInvalidationRule,
    BaselineMetricRule,
    ForecastArtifactReference,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
)
from .forecast_baseline_evidence import (
    ActualFactObservation,
    CostApplicability,
    ForecastErrorMetric,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
    TieBreakRule,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_finite,
    _require_sha256,
    _require_token,
    _utc_text,
)
from .forecast_baseline_forecast_evidence import forecast_artifact_reference_payload


@dataclass(frozen=True)
class PairedForecastBaselineRow:
    """One same-window comparison referencing one sealed actual fact."""

    period_end: date
    metric_code: str
    forecast_id: str
    forecast_content_hash: str
    forecast_value: Decimal
    baseline_value: Decimal
    actual: ActualFactObservation

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "paired metric_code")
        _require_token(self.forecast_id, "paired forecast_id")
        _require_sha256(self.forecast_content_hash, "paired forecast_content_hash")
        _require_finite(self.forecast_value, "forecast_value")
        _require_finite(self.baseline_value, "baseline_value")
        if self.period_end != self.actual.period_end or self.metric_code != self.actual.metric_code:
            raise ValueError("paired row key must match its exact actual fact")


@dataclass(frozen=True)
class TrialMetricComparison:
    """Recomputed paired error and promotion gate for one metric."""

    metric_code: str
    error_metric: ForecastErrorMetric
    forecast_error: Decimal
    baseline_error: Decimal
    improvement: Decimal
    sample_count: int
    coverage: Decimal
    passes: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "comparison metric_code")
        for field_name, value in (
            ("forecast_error", self.forecast_error),
            ("baseline_error", self.baseline_error),
            ("improvement", self.improvement),
            ("coverage", self.coverage),
        ):
            _require_finite(value, field_name)
        if self.forecast_error < 0 or self.baseline_error < 0:
            raise ValueError("comparison errors cannot be negative")
        if isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ValueError("comparison sample_count cannot be negative")
        if not Decimal("0") <= self.coverage <= Decimal("1"):
            raise ValueError("comparison coverage must be within [0, 1]")
        if self.passes != (not self.reason_codes):
            raise ValueError("comparison pass state must match reason codes")


@dataclass(frozen=True)
class InvalidationRuleOutcome:
    """Sealed result of applying one invalidation rule to period errors."""

    rule_code: str
    metric_code: str
    operator: InvalidationOperator
    threshold: Decimal
    consecutive_periods: int
    observed_errors: tuple[tuple[date, Decimal], ...]
    triggered_at: date | None
    passes: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.rule_code, "invalidation outcome rule_code")
        _require_token(self.metric_code, "invalidation outcome metric_code")
        _require_finite(self.threshold, "invalidation outcome threshold")
        if isinstance(self.consecutive_periods, bool) or self.consecutive_periods < 1:
            raise ValueError("invalidation outcome consecutive_periods must be positive")
        periods = tuple(item[0] for item in self.observed_errors)
        if periods != tuple(sorted(periods)) or len(periods) != len(set(periods)):
            raise ValueError("invalidation observed errors must be unique and ordered")
        for _, error in self.observed_errors:
            _require_finite(error, "invalidation observed error")
            if error < 0:
                raise ValueError("invalidation observed error cannot be negative")
        expected_reasons = (
            (f"invalidation_rule_triggered:{self.rule_code}",)
            if self.triggered_at is not None
            else ()
        )
        if self.reason_codes != expected_reasons or self.passes != (self.triggered_at is None):
            raise ValueError("invalidation outcome state is inconsistent")


@dataclass(frozen=True)
class ForecastBaselineTrialResult:
    """Complete same-window R1 comparison bound to exact baseline evidence."""

    result_id: str
    result_version: str
    owner: str
    research_trial: ResearchTrialAuthorization
    spec_id: str
    spec_version: str
    spec_content_hash: str
    baseline_artifact_id: str
    baseline_artifact_version: str
    baseline_artifact_content_hash: str
    expected_period_ends: tuple[date, ...]
    metric_rules: tuple[BaselineMetricRule, ...]
    metric_evaluation_order: tuple[str, ...]
    tie_break_rule: TieBreakRule
    cost_rule: BaselineCostRule
    invalidation_applicability: InvalidationApplicability
    invalidation_rules: tuple[BaselineInvalidationRule, ...]
    invalidation_not_applicable_reason: str
    forecasts: tuple[ForecastArtifactReference, ...]
    paired_rows: tuple[PairedForecastBaselineRow, ...]
    actual_manifest: EvaluationActualManifest
    metric_comparisons: tuple[TrialMetricComparison, ...]
    invalidation_outcomes: tuple[InvalidationRuleOutcome, ...]
    evaluated_at: datetime
    valid_until: datetime
    eligible_for_promotion: bool
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_version: str,
        owner: str,
        research_trial: ResearchTrialAuthorization,
        spec: ForecastBaselineSpec,
        artifact: ForecastBaselineArtifact,
        paired_rows: tuple[PairedForecastBaselineRow, ...],
        actual_manifest: EvaluationActualManifest,
        evaluated_at: datetime,
        valid_until: datetime,
    ) -> ForecastBaselineTrialResult:
        """Recompute paired errors and seal the complete trial result."""

        if spec.cost_rule.applicability is CostApplicability.APPLICABLE:
            raise ValueError("applicable cost rule requires executed cost evidence")
        if (
            artifact.spec_id != spec.spec_id
            or artifact.spec_version != spec.spec_version
            or artifact.spec_content_hash != spec.content_hash
            or artifact.evaluation_policy != spec.evaluation_policy
            or artifact.pit_inputs != spec.pit_inputs
            or artifact.expected_period_ends != spec.expected_period_ends
            or artifact.subject_code != spec.subject_code
            or artifact.industry_code != spec.industry_code
            or artifact.candidate_scenario != spec.candidate_scenario
            or artifact.horizon_quarters != spec.horizon_quarters
            or artifact.calendar_schedule != spec.calendar_schedule
            or artifact.period_horizons != spec.period_horizons
            or artifact.family != spec.family
            or artifact.computation_method != spec.computation_method
            or artifact.computation_code_version != spec.computation_code_version
            or artifact.family_parameter_version != spec.family_parameter_version
            or artifact.family_parameter_hash != spec.family_parameter_hash
            or artifact.seasonal_lag_periods != spec.seasonal_lag_periods
        ):
            raise ValueError("baseline artifact does not match the approved spec")
        expected_metric_codes = tuple(item.metric_code for item in spec.metric_rules)
        forecast_origin_at = min(item.as_of_time for item in artifact.forecasts)
        if (
            research_trial.baseline_spec_id != spec.spec_id
            or research_trial.baseline_spec_version != spec.spec_version
            or research_trial.baseline_spec_content_hash != spec.content_hash
            or research_trial.expected_period_ends != spec.expected_period_ends
            or research_trial.metric_codes != expected_metric_codes
            or research_trial.calendar_schedule_hash != spec.calendar_schedule.content_hash
            or research_trial.evaluation_policy != spec.evaluation_policy
            or research_trial.baseline_spec_approved_at != spec.approved_at
            or research_trial.forecast_origin_at != forecast_origin_at
            or not research_trial.activated_at <= evaluated_at < research_trial.valid_until
        ):
            raise ValueError("research trial authorization does not match the approved spec")
        upstream_valid_until = min(
            spec.valid_until,
            artifact.valid_until,
            research_trial.valid_until,
        )
        if not (spec.approved_at <= artifact.produced_at <= evaluated_at < upstream_valid_until):
            raise ValueError("trial evaluation is outside an active upstream window")
        if not evaluated_at < valid_until <= upstream_valid_until:
            raise ValueError("trial validity exceeds an upstream validity window")
        ordered_rows = tuple(
            sorted(paired_rows, key=lambda item: (item.period_end, item.metric_code))
        )
        _validate_actual_manifest_membership(
            actual_manifest=actual_manifest,
            rows=ordered_rows,
            evaluated_at=evaluated_at,
        )
        comparisons = _calculate_metric_comparisons(
            spec,
            artifact,
            ordered_rows,
            actual_manifest,
            evaluated_at,
        )
        invalidation_outcomes = _calculate_invalidation_outcomes(
            invalidation_rules=spec.invalidation_rules,
            metric_rules=spec.metric_rules,
            rows=ordered_rows,
        )
        eligible = all(item.passes for item in comparisons) and all(
            item.passes for item in invalidation_outcomes
        )
        content_hash = _hash_payload(
            _trial_payload(
                result_id=result_id,
                result_version=result_version,
                owner=owner,
                research_trial=research_trial,
                spec_id=spec.spec_id,
                spec_version=spec.spec_version,
                spec_content_hash=spec.content_hash,
                baseline_artifact_id=artifact.artifact_id,
                baseline_artifact_version=artifact.artifact_version,
                baseline_artifact_content_hash=artifact.content_hash,
                expected_period_ends=spec.expected_period_ends,
                metric_rules=spec.metric_rules,
                metric_evaluation_order=spec.metric_evaluation_order,
                tie_break_rule=spec.tie_break_rule,
                cost_rule=spec.cost_rule,
                invalidation_applicability=spec.invalidation_applicability,
                invalidation_rules=spec.invalidation_rules,
                invalidation_not_applicable_reason=spec.invalidation_not_applicable_reason,
                forecasts=artifact.forecasts,
                paired_rows=ordered_rows,
                actual_manifest=actual_manifest,
                metric_comparisons=comparisons,
                invalidation_outcomes=invalidation_outcomes,
                evaluated_at=evaluated_at,
                valid_until=valid_until,
                eligible_for_promotion=eligible,
            )
        )
        return cls(
            result_id=result_id,
            result_version=result_version,
            owner=owner,
            research_trial=research_trial,
            spec_id=spec.spec_id,
            spec_version=spec.spec_version,
            spec_content_hash=spec.content_hash,
            baseline_artifact_id=artifact.artifact_id,
            baseline_artifact_version=artifact.artifact_version,
            baseline_artifact_content_hash=artifact.content_hash,
            expected_period_ends=spec.expected_period_ends,
            metric_rules=spec.metric_rules,
            metric_evaluation_order=spec.metric_evaluation_order,
            tie_break_rule=spec.tie_break_rule,
            cost_rule=spec.cost_rule,
            invalidation_applicability=spec.invalidation_applicability,
            invalidation_rules=spec.invalidation_rules,
            invalidation_not_applicable_reason=spec.invalidation_not_applicable_reason,
            forecasts=artifact.forecasts,
            paired_rows=ordered_rows,
            actual_manifest=actual_manifest,
            metric_comparisons=comparisons,
            invalidation_outcomes=invalidation_outcomes,
            evaluated_at=evaluated_at,
            valid_until=valid_until,
            eligible_for_promotion=eligible,
            content_hash=content_hash,
        )

    def __post_init__(self) -> None:
        _require_token(self.result_id, "result_id")
        _require_token(self.result_version, "result_version")
        if self.owner != "equity":
            raise ValueError("forecast baseline trial result owner must be equity")
        if (
            self.research_trial.baseline_spec_id != self.spec_id
            or self.research_trial.baseline_spec_version != self.spec_version
            or self.research_trial.baseline_spec_content_hash != self.spec_content_hash
            or self.research_trial.expected_period_ends != self.expected_period_ends
            or self.research_trial.metric_codes
            != tuple(item.metric_code for item in self.metric_rules)
            or not self.research_trial.activated_at
            <= self.evaluated_at
            < self.research_trial.valid_until
            or self.valid_until > self.research_trial.valid_until
        ):
            raise ValueError("result research trial authorization is inconsistent")
        _require_sha256(self.spec_content_hash, "result spec_content_hash")
        _require_sha256(
            self.baseline_artifact_content_hash,
            "result baseline_artifact_content_hash",
        )
        _require_aware(self.evaluated_at, "result evaluated_at")
        _require_aware(self.valid_until, "result valid_until")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("trial result validity must follow evaluation")
        if self.cost_rule.applicability is CostApplicability.APPLICABLE:
            raise ValueError("applicable cost rule requires executed cost evidence")
        if self.invalidation_applicability is InvalidationApplicability.APPLICABLE:
            if not self.invalidation_rules or self.invalidation_not_applicable_reason:
                raise ValueError("applicable invalidation policy requires non-empty rules")
        elif self.invalidation_applicability is InvalidationApplicability.NOT_APPLICABLE:
            if self.invalidation_rules or not self.invalidation_not_applicable_reason.strip():
                raise ValueError("non-applicable invalidation policy requires rationale")
        else:
            raise ValueError("invalidation applicability is invalid")
        _validate_actual_manifest_membership(
            actual_manifest=self.actual_manifest,
            rows=self.paired_rows,
            evaluated_at=self.evaluated_at,
        )
        recomputed_comparisons = _summarize_metric_comparisons(
            expected_period_ends=self.expected_period_ends,
            metric_rules=self.metric_rules,
            metric_evaluation_order=self.metric_evaluation_order,
            tie_break_rule=self.tie_break_rule,
            rows=self.paired_rows,
        )
        if self.metric_comparisons != recomputed_comparisons:
            raise ValueError("trial metric comparisons do not match paired rows")
        recomputed_invalidations = _calculate_invalidation_outcomes(
            invalidation_rules=self.invalidation_rules,
            metric_rules=self.metric_rules,
            rows=self.paired_rows,
        )
        if self.invalidation_outcomes != recomputed_invalidations:
            raise ValueError("trial invalidation outcomes do not match paired rows")
        expected_eligibility = all(item.passes for item in recomputed_comparisons) and all(
            item.passes for item in recomputed_invalidations
        )
        if self.eligible_for_promotion != expected_eligibility:
            raise ValueError("trial result eligibility does not match sealed gates")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("trial result must remain research-only")
        _require_sha256(self.content_hash, "trial result content_hash")
        payload = _trial_payload(
            result_id=self.result_id,
            result_version=self.result_version,
            owner=self.owner,
            research_trial=self.research_trial,
            spec_id=self.spec_id,
            spec_version=self.spec_version,
            spec_content_hash=self.spec_content_hash,
            baseline_artifact_id=self.baseline_artifact_id,
            baseline_artifact_version=self.baseline_artifact_version,
            baseline_artifact_content_hash=self.baseline_artifact_content_hash,
            expected_period_ends=self.expected_period_ends,
            metric_rules=self.metric_rules,
            metric_evaluation_order=self.metric_evaluation_order,
            tie_break_rule=self.tie_break_rule,
            cost_rule=self.cost_rule,
            invalidation_applicability=self.invalidation_applicability,
            invalidation_rules=self.invalidation_rules,
            invalidation_not_applicable_reason=self.invalidation_not_applicable_reason,
            forecasts=self.forecasts,
            paired_rows=self.paired_rows,
            actual_manifest=self.actual_manifest,
            metric_comparisons=self.metric_comparisons,
            invalidation_outcomes=self.invalidation_outcomes,
            evaluated_at=self.evaluated_at,
            valid_until=self.valid_until,
            eligible_for_promotion=self.eligible_for_promotion,
        )
        if self.content_hash != _hash_payload(payload):
            raise ValueError("forecast baseline trial result content hash mismatch")


def _validate_actual_manifest_membership(
    *,
    actual_manifest: EvaluationActualManifest,
    rows: tuple[PairedForecastBaselineRow, ...],
    evaluated_at: datetime,
) -> None:
    if actual_manifest.produced_at > evaluated_at:
        raise ValueError("actual manifest was unavailable at evaluation time")
    if tuple(item.actual for item in rows) != actual_manifest.members:
        raise ValueError("paired actual facts must exactly match actual manifest members")
    if any(item.available_at > evaluated_at for item in actual_manifest.members):
        raise ValueError("actual manifest contains future-unavailable facts")


def _calculate_metric_comparisons(
    spec: ForecastBaselineSpec,
    artifact: ForecastBaselineArtifact,
    rows: tuple[PairedForecastBaselineRow, ...],
    actual_manifest: EvaluationActualManifest,
    evaluated_at: datetime,
) -> tuple[TrialMetricComparison, ...]:
    expected_keys = tuple(
        (period, rule.metric_code)
        for period in spec.expected_period_ends
        for rule in spec.metric_rules
    )
    if tuple((item.period_end, item.metric_code) for item in rows) != expected_keys:
        raise ValueError("paired rows require the full period-metric cross-product")
    forecasts = {item.target_period_end: item for item in artifact.forecasts}
    predictions = {(item.period_end, item.metric_code): item for item in artifact.predictions}
    evaluation_calendar = (
        artifact.pit_inputs[0].calendar_id,
        artifact.pit_inputs[0].calendar_version,
        artifact.pit_inputs[0].calendar_content_hash,
    )
    if (
        actual_manifest.subject_code != artifact.subject_code
        or actual_manifest.industry_code != artifact.industry_code
        or (
            actual_manifest.calendar_id,
            actual_manifest.calendar_version,
            actual_manifest.calendar_content_hash,
        )
        != evaluation_calendar
    ):
        raise ValueError("actual manifest scope or calendar does not match artifact")
    for row in rows:
        forecast = forecasts[row.period_end]
        baseline = predictions[(row.period_end, row.metric_code)]
        forecast_values = dict(forecast.metric_values)
        forecast_units = dict(forecast.metric_units)
        actual = row.actual
        if (
            row.forecast_id != forecast.forecast_id
            or row.forecast_content_hash != forecast.forecast_content_hash
            or row.forecast_value != forecast_values[row.metric_code]
            or actual.unit != forecast_units[row.metric_code]
            or row.baseline_value != baseline.value
            or actual.unit != baseline.unit
            or actual.subject_code != artifact.subject_code
            or actual.industry_code != artifact.industry_code
            or actual.available_at > evaluated_at
        ):
            raise ValueError("paired row does not match forecast/baseline/PIT evidence")
    return _summarize_metric_comparisons(
        expected_period_ends=spec.expected_period_ends,
        metric_rules=spec.metric_rules,
        metric_evaluation_order=spec.metric_evaluation_order,
        tie_break_rule=spec.tie_break_rule,
        rows=rows,
    )


def _summarize_metric_comparisons(
    *,
    expected_period_ends: tuple[date, ...],
    metric_rules: tuple[BaselineMetricRule, ...],
    metric_evaluation_order: tuple[str, ...],
    tie_break_rule: TieBreakRule,
    rows: tuple[PairedForecastBaselineRow, ...],
) -> tuple[TrialMetricComparison, ...]:
    expected_keys = tuple(
        (period, rule.metric_code) for period in expected_period_ends for rule in metric_rules
    )
    if tuple((item.period_end, item.metric_code) for item in rows) != expected_keys:
        raise ValueError("paired rows require the full period-metric cross-product")
    result: list[TrialMetricComparison] = []
    for rule in metric_rules:
        metric_rows = tuple(item for item in rows if item.metric_code == rule.metric_code)
        usable = tuple(
            item
            for item in metric_rows
            if not (
                rule.error_metric is ForecastErrorMetric.MAPE
                and item.actual.value == 0
                and rule.mape_zero_actual_rule is MapeZeroActualRule.EXCLUDE_WITH_COVERAGE_PENALTY
            )
        )
        if (
            rule.error_metric is ForecastErrorMetric.MAPE
            and rule.mape_zero_actual_rule is MapeZeroActualRule.BLOCK
            and any(item.actual.value == 0 for item in metric_rows)
        ):
            raise ValueError("MAPE zero-actual rule blocks this paired comparison")
        sample_count = len(usable)
        coverage = Decimal(sample_count) / Decimal(len(metric_rows))
        if usable:
            forecast_errors = tuple(
                _row_error(item.forecast_value, item.actual.value, rule.error_metric)
                for item in usable
            )
            baseline_errors = tuple(
                _row_error(item.baseline_value, item.actual.value, rule.error_metric)
                for item in usable
            )
            forecast_error = sum(forecast_errors, Decimal("0")) / Decimal(sample_count)
            baseline_error = sum(baseline_errors, Decimal("0")) / Decimal(sample_count)
        else:
            forecast_error = Decimal("0")
            baseline_error = Decimal("0")
        improvement = baseline_error - forecast_error
        reasons: list[str] = []
        if sample_count < rule.minimum_sample_count:
            reasons.append("minimum_sample_count_not_met")
        if coverage < rule.minimum_coverage:
            reasons.append("minimum_coverage_not_met")
        if forecast_error > rule.maximum_forecast_error:
            reasons.append("maximum_forecast_error_breached")
        if improvement < rule.minimum_improvement:
            reasons.append("minimum_improvement_not_met")
        if improvement == 0 and tie_break_rule is TieBreakRule.BASELINE_WINS:
            reasons.append("baseline_wins_tie")
        result.append(
            TrialMetricComparison(
                metric_code=rule.metric_code,
                error_metric=rule.error_metric,
                forecast_error=forecast_error,
                baseline_error=baseline_error,
                improvement=improvement,
                sample_count=sample_count,
                coverage=coverage,
                passes=not reasons,
                reason_codes=tuple(reasons),
            )
        )
    by_code = {item.metric_code: item for item in result}
    return tuple(by_code[code] for code in metric_evaluation_order)


def _calculate_invalidation_outcomes(
    *,
    invalidation_rules: tuple[BaselineInvalidationRule, ...],
    metric_rules: tuple[BaselineMetricRule, ...],
    rows: tuple[PairedForecastBaselineRow, ...],
) -> tuple[InvalidationRuleOutcome, ...]:
    metric_rule_by_code = {item.metric_code: item for item in metric_rules}
    outcomes: list[InvalidationRuleOutcome] = []
    for rule in invalidation_rules:
        metric_rule = metric_rule_by_code[rule.metric_code]
        metric_rows = tuple(item for item in rows if item.metric_code == rule.metric_code)
        observed_errors: list[tuple[date, Decimal]] = []
        consecutive_hits = 0
        triggered_at: date | None = None
        for row in metric_rows:
            if metric_rule.error_metric is ForecastErrorMetric.MAPE and row.actual.value == 0:
                consecutive_hits = 0
                if metric_rule.mape_zero_actual_rule is MapeZeroActualRule.BLOCK:
                    raise ValueError("MAPE zero-actual rule blocks invalidation evaluation")
                continue
            error = _row_error(
                row.forecast_value,
                row.actual.value,
                metric_rule.error_metric,
            )
            observed_errors.append((row.period_end, error))
            if _matches_invalidation(error, rule.operator, rule.threshold):
                consecutive_hits += 1
                if consecutive_hits >= rule.consecutive_periods and triggered_at is None:
                    triggered_at = row.period_end
            else:
                consecutive_hits = 0
        reasons = (
            (f"invalidation_rule_triggered:{rule.rule_code}",) if triggered_at is not None else ()
        )
        outcomes.append(
            InvalidationRuleOutcome(
                rule_code=rule.rule_code,
                metric_code=rule.metric_code,
                operator=rule.operator,
                threshold=rule.threshold,
                consecutive_periods=rule.consecutive_periods,
                observed_errors=tuple(observed_errors),
                triggered_at=triggered_at,
                passes=triggered_at is None,
                reason_codes=reasons,
            )
        )
    return tuple(outcomes)


def _matches_invalidation(
    value: Decimal,
    operator: InvalidationOperator,
    threshold: Decimal,
) -> bool:
    if operator is InvalidationOperator.GREATER_THAN:
        return value > threshold
    if operator is InvalidationOperator.GREATER_THAN_OR_EQUAL:
        return value >= threshold
    if operator is InvalidationOperator.LESS_THAN:
        return value < threshold
    if operator is InvalidationOperator.LESS_THAN_OR_EQUAL:
        return value <= threshold
    raise ValueError("unsupported invalidation operator")


def _row_error(
    predicted: Decimal,
    actual: Decimal,
    metric: ForecastErrorMetric,
) -> Decimal:
    absolute = abs(predicted - actual)
    if metric is ForecastErrorMetric.MAE:
        return absolute
    if actual == 0:
        raise ValueError("MAPE cannot divide by zero")
    return absolute / abs(actual)


def _trial_payload(
    *,
    result_id: str,
    result_version: str,
    owner: str,
    research_trial: ResearchTrialAuthorization,
    spec_id: str,
    spec_version: str,
    spec_content_hash: str,
    baseline_artifact_id: str,
    baseline_artifact_version: str,
    baseline_artifact_content_hash: str,
    expected_period_ends: tuple[date, ...],
    metric_rules: tuple[BaselineMetricRule, ...],
    metric_evaluation_order: tuple[str, ...],
    tie_break_rule: TieBreakRule,
    cost_rule: BaselineCostRule,
    invalidation_applicability: InvalidationApplicability,
    invalidation_rules: tuple[BaselineInvalidationRule, ...],
    invalidation_not_applicable_reason: str,
    forecasts: tuple[ForecastArtifactReference, ...],
    paired_rows: tuple[PairedForecastBaselineRow, ...],
    actual_manifest: EvaluationActualManifest,
    metric_comparisons: tuple[TrialMetricComparison, ...],
    invalidation_outcomes: tuple[InvalidationRuleOutcome, ...],
    evaluated_at: datetime,
    valid_until: datetime,
    eligible_for_promotion: bool,
) -> dict[str, object]:
    return {
        "schema": "r1-forecast-baseline-trial-result.v3",
        "result": [result_id, result_version, owner],
        "research_trial": {
            "identity": [
                research_trial.trial_id,
                research_trial.trial_version,
                research_trial.trial_content_hash,
            ],
            "authority": [
                research_trial.owner,
                research_trial.capability,
                research_trial.purpose,
                research_trial.status,
            ],
            "contract": [
                research_trial.split_spec_hash,
                research_trial.parameter_hash,
                research_trial.baseline_spec_id,
                research_trial.baseline_spec_version,
                research_trial.baseline_spec_content_hash,
                [item.isoformat() for item in research_trial.expected_period_ends],
                list(research_trial.metric_codes),
                research_trial.calendar_schedule_hash,
                [
                    research_trial.evaluation_policy.policy_id,
                    research_trial.evaluation_policy.policy_version,
                    research_trial.evaluation_policy.policy_content_hash,
                    research_trial.evaluation_policy.owner,
                    research_trial.evaluation_policy.actual_dataset,
                    research_trial.evaluation_policy.actual_knowledge_scope,
                    research_trial.evaluation_policy.actual_revision_rule.value,
                    research_trial.evaluation_policy.actual_vintage_rule.value,
                    research_trial.evaluation_policy.forecast_freeze_rule.value,
                    _utc_text(research_trial.evaluation_policy.forecast_knowledge_cutoff_at),
                    _utc_text(research_trial.evaluation_policy.forecast_submission_deadline_at),
                    _utc_text(research_trial.evaluation_policy.valid_until),
                ],
                _utc_text(research_trial.baseline_spec_approved_at),
                _utc_text(research_trial.forecast_origin_at),
            ],
            "window": [
                _utc_text(research_trial.activated_at),
                _utc_text(research_trial.recorded_at),
                _utc_text(research_trial.valid_until),
            ],
        },
        "spec": [spec_id, spec_version, spec_content_hash],
        "baseline_artifact": [
            baseline_artifact_id,
            baseline_artifact_version,
            baseline_artifact_content_hash,
        ],
        "expected_periods": [item.isoformat() for item in expected_period_ends],
        "metric_rule_hash": _hash_payload(
            {
                "rules": [
                    [
                        item.metric_code,
                        item.error_metric.value,
                        _decimal_text(item.maximum_forecast_error),
                        _decimal_text(item.minimum_improvement),
                        item.minimum_sample_count,
                        _decimal_text(item.minimum_coverage),
                        item.mape_zero_actual_rule.value,
                    ]
                    for item in metric_rules
                ],
                "evaluation_order": list(metric_evaluation_order),
                "tie_rule": tie_break_rule.value,
                "cost": [
                    cost_rule.applicability.value,
                    cost_rule.cost_model_version,
                    cost_rule.cost_model_content_hash,
                    cost_rule.not_applicable_reason,
                ],
                "invalidation_rules": [
                    [
                        item.rule_code,
                        item.metric_code,
                        item.operator.value,
                        _decimal_text(item.threshold),
                        item.consecutive_periods,
                    ]
                    for item in invalidation_rules
                ],
                "invalidation_policy": [
                    invalidation_applicability.value,
                    invalidation_not_applicable_reason,
                ],
            }
        ),
        "forecasts": [forecast_artifact_reference_payload(item) for item in forecasts],
        "actual_manifest": {
            "identity": [
                actual_manifest.manifest_id,
                actual_manifest.manifest_version,
                actual_manifest.manifest_content_hash,
                actual_manifest.owner,
            ],
            "seal_hash": actual_manifest.seal_hash,
            "as_of_time": _utc_text(actual_manifest.as_of_time),
            "produced_at": _utc_text(actual_manifest.produced_at),
            "quality": [
                actual_manifest.knowledge_scope,
                actual_manifest.is_verified,
                _decimal_text(actual_manifest.coverage_ratio),
                actual_manifest.missing_count,
                actual_manifest.estimated_count,
                actual_manifest.unknown_count,
            ],
            "selected_versions_hash": actual_manifest.selected_versions_hash,
        },
        "paired_rows": [
            [
                item.period_end.isoformat(),
                item.metric_code,
                item.forecast_id,
                item.forecast_content_hash,
                _decimal_text(item.forecast_value),
                _decimal_text(item.baseline_value),
                {
                    "scope": [item.actual.subject_code, item.actual.industry_code],
                    "period": item.actual.period_end.isoformat(),
                    "metric": item.actual.metric_code,
                    "value": _decimal_text(item.actual.value),
                    "unit": item.actual.unit,
                    "source_fact": [
                        item.actual.source_fact_id,
                        item.actual.source_fact_version,
                        item.actual.source_fact_content_hash,
                    ],
                    "observation_hash": item.actual.observation_hash,
                    "effective_at": _utc_text(item.actual.effective_at),
                    "available_at": _utc_text(item.actual.available_at),
                    "vintage": [
                        item.actual.vintage_id,
                        item.actual.vintage_version,
                        item.actual.vintage_content_hash,
                    ],
                    "manifest": [
                        item.actual.pit_manifest_id,
                        item.actual.pit_manifest_hash,
                    ],
                    "manifest_member": [
                        item.actual.manifest_member_id,
                        item.actual.manifest_member_version,
                        item.actual.manifest_member_content_hash,
                    ],
                    "calendar": [
                        item.actual.calendar_id,
                        item.actual.calendar_version,
                        item.actual.calendar_content_hash,
                    ],
                },
            ]
            for item in paired_rows
        ],
        "comparisons": [
            [
                item.metric_code,
                item.error_metric.value,
                _decimal_text(item.forecast_error),
                _decimal_text(item.baseline_error),
                _decimal_text(item.improvement),
                item.sample_count,
                _decimal_text(item.coverage),
                item.passes,
                list(item.reason_codes),
            ]
            for item in metric_comparisons
        ],
        "invalidation_outcomes": [
            [
                item.rule_code,
                item.metric_code,
                item.operator.value,
                _decimal_text(item.threshold),
                item.consecutive_periods,
                [
                    [period.isoformat(), _decimal_text(error)]
                    for period, error in item.observed_errors
                ],
                item.triggered_at.isoformat() if item.triggered_at is not None else None,
                item.passes,
                list(item.reason_codes),
            ]
            for item in invalidation_outcomes
        ],
        "evaluated_at": _utc_text(evaluated_at),
        "valid_until": _utc_text(valid_until),
        "eligible_for_promotion": eligible_for_promotion,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


__all__ = [
    "EvaluationActualManifest",
    "ForecastBaselineTrialResult",
    "InvalidationRuleOutcome",
    "PairedForecastBaselineRow",
    "TrialMetricComparison",
]
