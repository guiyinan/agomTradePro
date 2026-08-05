"""R1 approved baseline specs, forecast references and sealed artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .forecast_baseline_authority import ForecastEvaluationPolicy
from .forecast_baseline_evidence import (
    BaselineApprovalStatus,
    BaselineComputationMethod,
    BaselineFamily,
    BaselinePITInputSpec,
    CostApplicability,
    ForecastCalendarScheduleEvidence,
    ForecastErrorMetric,
    ForecastPeriodHorizon,
    ForecastScenario,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
    TieBreakRule,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_finite,
    _require_sha256,
    _require_text,
    _require_token,
    _utc_text,
)
from .forecast_baseline_forecast_evidence import (
    BaselinePredictionObservation,
    ForecastArtifactReference,
    forecast_artifact_reference_payload,
)


@dataclass(frozen=True)
class BaselineMetricRule:
    """Pre-registered metric, coverage and improvement gate."""

    metric_code: str
    error_metric: ForecastErrorMetric
    maximum_forecast_error: Decimal
    minimum_improvement: Decimal
    minimum_sample_count: int
    minimum_coverage: Decimal
    mape_zero_actual_rule: MapeZeroActualRule

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "metric_code")
        _require_finite(self.maximum_forecast_error, "maximum_forecast_error")
        _require_finite(self.minimum_improvement, "minimum_improvement")
        _require_finite(self.minimum_coverage, "minimum_coverage")
        if self.maximum_forecast_error < 0 or self.minimum_improvement < 0:
            raise ValueError("metric error and improvement thresholds cannot be negative")
        if isinstance(self.minimum_sample_count, bool) or self.minimum_sample_count < 1:
            raise ValueError("minimum_sample_count must be positive")
        if not Decimal("0") < self.minimum_coverage <= Decimal("1"):
            raise ValueError("minimum_coverage must be within (0, 1]")


@dataclass(frozen=True)
class BaselineCostRule:
    """Explicit cost-model identity or explicit non-applicability rationale."""

    applicability: CostApplicability
    cost_model_version: str
    cost_model_content_hash: str
    not_applicable_reason: str

    def __post_init__(self) -> None:
        if self.applicability is CostApplicability.APPLICABLE:
            _require_token(self.cost_model_version, "cost_model_version")
            _require_sha256(self.cost_model_content_hash, "cost_model_content_hash")
            if self.not_applicable_reason:
                raise ValueError("applicable cost rule cannot carry a non-applicable reason")
        elif self.applicability is CostApplicability.NOT_APPLICABLE:
            if self.cost_model_version or self.cost_model_content_hash:
                raise ValueError("non-applicable cost rule cannot carry model identity")
            _require_text(self.not_applicable_reason, "not_applicable_reason")
        else:
            raise ValueError("cost applicability is invalid")


@dataclass(frozen=True)
class BaselineInvalidationRule:
    """Versioned condition that invalidates an otherwise approved spec."""

    rule_code: str
    metric_code: str
    operator: InvalidationOperator
    threshold: Decimal
    consecutive_periods: int

    def __post_init__(self) -> None:
        _require_token(self.rule_code, "rule_code")
        _require_token(self.metric_code, "metric_code")
        _require_finite(self.threshold, "invalidation threshold")
        if isinstance(self.consecutive_periods, bool) or self.consecutive_periods < 1:
            raise ValueError("consecutive_periods must be positive")


@dataclass(frozen=True)
class ForecastBaselineSpec:
    """Equity-approved, versioned baseline evaluation specification."""

    spec_id: str
    spec_version: str
    owner: str
    approval_evidence_id: str
    approval_evidence_version: str
    approval_evidence_content_hash: str
    approval_owner: str
    approval_status: BaselineApprovalStatus
    evaluation_policy: ForecastEvaluationPolicy
    subject_code: str
    industry_code: str
    candidate_scenario: ForecastScenario
    horizon_quarters: int
    family: BaselineFamily
    computation_method: BaselineComputationMethod
    computation_code_version: str
    family_parameter_version: str
    family_parameter_hash: str
    seasonal_lag_periods: int | None
    pit_inputs: tuple[BaselinePITInputSpec, ...]
    training_window_start: date
    training_window_end: date
    expected_period_ends: tuple[date, ...]
    calendar_schedule: ForecastCalendarScheduleEvidence
    period_horizons: tuple[ForecastPeriodHorizon, ...]
    metric_rules: tuple[BaselineMetricRule, ...]
    metric_evaluation_order: tuple[str, ...]
    tie_break_rule: TieBreakRule
    cost_rule: BaselineCostRule
    invalidation_applicability: InvalidationApplicability
    invalidation_rules: tuple[BaselineInvalidationRule, ...]
    invalidation_not_applicable_reason: str
    approved_at: datetime
    approval_recorded_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        spec_id: str,
        spec_version: str,
        owner: str,
        approval_evidence_id: str,
        approval_evidence_version: str,
        approval_evidence_content_hash: str,
        approval_owner: str,
        approval_status: BaselineApprovalStatus,
        evaluation_policy: ForecastEvaluationPolicy,
        subject_code: str,
        industry_code: str,
        candidate_scenario: ForecastScenario,
        horizon_quarters: int,
        family: BaselineFamily,
        computation_method: BaselineComputationMethod,
        computation_code_version: str,
        family_parameter_version: str,
        family_parameter_hash: str,
        seasonal_lag_periods: int | None,
        pit_inputs: tuple[BaselinePITInputSpec, ...],
        training_window_start: date,
        training_window_end: date,
        expected_period_ends: tuple[date, ...],
        calendar_schedule: ForecastCalendarScheduleEvidence,
        period_horizons: tuple[ForecastPeriodHorizon, ...],
        metric_rules: tuple[BaselineMetricRule, ...],
        metric_evaluation_order: tuple[str, ...],
        tie_break_rule: TieBreakRule,
        cost_rule: BaselineCostRule,
        invalidation_applicability: InvalidationApplicability,
        invalidation_rules: tuple[BaselineInvalidationRule, ...],
        invalidation_not_applicable_reason: str,
        approved_at: datetime,
        approval_recorded_at: datetime,
        valid_until: datetime,
    ) -> ForecastBaselineSpec:
        """Order and seal one approved specification without inserting defaults."""

        ordered_inputs = tuple(sorted(pit_inputs, key=lambda item: item.input_role))
        ordered_metrics = tuple(sorted(metric_rules, key=lambda item: item.metric_code))
        ordered_invalidations = tuple(sorted(invalidation_rules, key=lambda item: item.rule_code))
        payload = _spec_payload(
            spec_id=spec_id,
            spec_version=spec_version,
            owner=owner,
            approval_evidence_id=approval_evidence_id,
            approval_evidence_version=approval_evidence_version,
            approval_evidence_content_hash=approval_evidence_content_hash,
            approval_owner=approval_owner,
            approval_status=approval_status,
            evaluation_policy=evaluation_policy,
            subject_code=subject_code,
            industry_code=industry_code,
            candidate_scenario=candidate_scenario,
            horizon_quarters=horizon_quarters,
            family=family,
            computation_method=computation_method,
            computation_code_version=computation_code_version,
            family_parameter_version=family_parameter_version,
            family_parameter_hash=family_parameter_hash,
            seasonal_lag_periods=seasonal_lag_periods,
            pit_inputs=ordered_inputs,
            training_window_start=training_window_start,
            training_window_end=training_window_end,
            expected_period_ends=expected_period_ends,
            calendar_schedule=calendar_schedule,
            period_horizons=period_horizons,
            metric_rules=ordered_metrics,
            metric_evaluation_order=metric_evaluation_order,
            tie_break_rule=tie_break_rule,
            cost_rule=cost_rule,
            invalidation_applicability=invalidation_applicability,
            invalidation_rules=ordered_invalidations,
            invalidation_not_applicable_reason=invalidation_not_applicable_reason,
            approved_at=approved_at,
            approval_recorded_at=approval_recorded_at,
            valid_until=valid_until,
        )
        return cls(
            spec_id=spec_id,
            spec_version=spec_version,
            owner=owner,
            approval_evidence_id=approval_evidence_id,
            approval_evidence_version=approval_evidence_version,
            approval_evidence_content_hash=approval_evidence_content_hash,
            approval_owner=approval_owner,
            approval_status=approval_status,
            evaluation_policy=evaluation_policy,
            subject_code=subject_code,
            industry_code=industry_code,
            candidate_scenario=candidate_scenario,
            horizon_quarters=horizon_quarters,
            family=family,
            computation_method=computation_method,
            computation_code_version=computation_code_version,
            family_parameter_version=family_parameter_version,
            family_parameter_hash=family_parameter_hash,
            seasonal_lag_periods=seasonal_lag_periods,
            pit_inputs=ordered_inputs,
            training_window_start=training_window_start,
            training_window_end=training_window_end,
            expected_period_ends=expected_period_ends,
            calendar_schedule=calendar_schedule,
            period_horizons=period_horizons,
            metric_rules=ordered_metrics,
            metric_evaluation_order=metric_evaluation_order,
            tie_break_rule=tie_break_rule,
            cost_rule=cost_rule,
            invalidation_applicability=invalidation_applicability,
            invalidation_rules=ordered_invalidations,
            invalidation_not_applicable_reason=invalidation_not_applicable_reason,
            approved_at=approved_at,
            approval_recorded_at=approval_recorded_at,
            valid_until=valid_until,
            content_hash=_hash_payload(payload),
        )

    def __post_init__(self) -> None:
        _require_token(self.spec_id, "spec_id")
        _require_token(self.spec_version, "spec_version")
        if self.owner != "equity":
            raise ValueError("forecast baseline spec owner must be equity")
        _require_token(self.approval_evidence_id, "approval_evidence_id")
        _require_token(self.approval_evidence_version, "approval_evidence_version")
        _require_sha256(
            self.approval_evidence_content_hash,
            "approval_evidence_content_hash",
        )
        if self.approval_owner != "equity":
            raise ValueError("baseline approval owner must be equity")
        if self.approval_status is not BaselineApprovalStatus.APPROVED:
            raise ValueError("baseline approval status must be approved")
        _require_token(self.subject_code, "subject_code")
        _require_token(self.industry_code, "industry_code")
        if not isinstance(self.candidate_scenario, ForecastScenario):
            raise ValueError("candidate_scenario must be a ForecastScenario")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("horizon_quarters must be positive")
        if self.family not in {
            BaselineFamily.SEASONAL_NAIVE,
            BaselineFamily.EXTERNAL_CONSENSUS,
        }:
            raise ValueError("baseline family has no implemented computation")
        if self.computation_method is not BaselineComputationMethod.DIRECT_APPROVED_SOURCE:
            raise ValueError("baseline computation method is not implemented")
        _require_token(self.computation_code_version, "computation_code_version")
        _require_token(self.family_parameter_version, "family_parameter_version")
        _require_sha256(self.family_parameter_hash, "family_parameter_hash")
        if self.family is BaselineFamily.SEASONAL_NAIVE:
            if (
                isinstance(self.seasonal_lag_periods, bool)
                or self.seasonal_lag_periods is None
                or self.seasonal_lag_periods < 1
            ):
                raise ValueError("seasonal baseline requires a positive approved lag")
        elif self.seasonal_lag_periods is not None:
            raise ValueError("non-seasonal baseline cannot carry a seasonal lag")
        _require_aware(self.approved_at, "approved_at")
        _require_aware(self.approval_recorded_at, "approval_recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.approved_at or self.approval_recorded_at < self.approved_at:
            raise ValueError("baseline spec validity must follow approval")
        if self.training_window_end < self.training_window_start:
            raise ValueError("training window is invalid")
        if (
            not self.expected_period_ends
            or self.expected_period_ends != tuple(sorted(self.expected_period_ends))
            or len(self.expected_period_ends) != len(set(self.expected_period_ends))
            or self.expected_period_ends[0] <= self.training_window_end
        ):
            raise ValueError("expected periods must be unique, ordered and out of training")
        horizon_targets = tuple(item.target_period_end for item in self.period_horizons)
        if (
            horizon_targets != self.expected_period_ends
            or len(horizon_targets) != len(set(horizon_targets))
            or max(item.horizon_quarters for item in self.period_horizons) != self.horizon_quarters
        ):
            raise ValueError("period horizon mapping must exactly cover the declared horizon")
        recomputed_horizons = tuple(
            ForecastPeriodHorizon.create(
                target_period_end=item.target_period_end,
                forecast_origin_at=item.forecast_origin_at,
                schedule=self.calendar_schedule,
            )
            for item in self.period_horizons
        )
        if self.period_horizons != recomputed_horizons:
            raise ValueError("period horizons must be derived from the calendar schedule")
        forecast_origins = {item.forecast_origin_at for item in self.period_horizons}
        if len(forecast_origins) != 1:
            raise ValueError("baseline period horizons must share one forecast origin")
        forecast_origin_at = next(iter(forecast_origins))
        if (
            not (
                self.approved_at
                <= self.approval_recorded_at
                <= self.evaluation_policy.forecast_knowledge_cutoff_at
                == forecast_origin_at
                <= self.evaluation_policy.forecast_submission_deadline_at
            )
            or self.evaluation_policy.forecast_submission_deadline_at.date()
            >= min(self.expected_period_ends)
            or self.valid_until > self.evaluation_policy.valid_until
        ):
            raise ValueError("forecast submission deadline is outside the approved window")
        if any(
            item.manifest_as_of_time > forecast_origin_at
            or item.manifest_produced_at > forecast_origin_at
            or any(member.source_available_at > forecast_origin_at for member in item.members)
            for item in self.pit_inputs
        ):
            raise ValueError("PIT evidence was not knowable at the forecast origin")
        input_roles = tuple(item.input_role for item in self.pit_inputs)
        metric_codes = tuple(item.metric_code for item in self.metric_rules)
        invalidation_codes = tuple(item.rule_code for item in self.invalidation_rules)
        if (
            not input_roles
            or input_roles != tuple(sorted(input_roles))
            or len(input_roles) != len(set(input_roles))
        ):
            raise ValueError("PIT input roles must be non-empty, unique and ordered")
        calendar_identities = {
            (item.calendar_id, item.calendar_version, item.calendar_content_hash)
            for item in self.pit_inputs
        }
        if len(calendar_identities) != 1:
            raise ValueError("all baseline inputs must use one exact evaluation calendar")
        calendar_identity = next(iter(calendar_identities))
        if (
            self.calendar_schedule.calendar_id,
            self.calendar_schedule.calendar_version,
            self.calendar_schedule.calendar_content_hash,
        ) != calendar_identity:
            raise ValueError("calendar schedule does not match PIT calendar identity")
        if any(
            (item.calendar_id, item.calendar_version, item.calendar_content_hash)
            != calendar_identity
            for item in self.period_horizons
        ):
            raise ValueError("period horizons must use the exact evaluation calendar")
        if any(
            tuple(member.target_period_end for member in item.members) != self.expected_period_ends
            for item in self.pit_inputs
        ):
            raise ValueError("each PIT input must map one member to every target period")
        if (
            not metric_codes
            or metric_codes != tuple(sorted(metric_codes))
            or len(metric_codes) != len(set(metric_codes))
        ):
            raise ValueError("metric rules must be non-empty, unique and ordered")
        if set(self.metric_evaluation_order) != set(metric_codes) or len(
            self.metric_evaluation_order
        ) != len(metric_codes):
            raise ValueError("tie-break order must cover each metric exactly once")
        if invalidation_codes != tuple(sorted(invalidation_codes)) or len(
            invalidation_codes
        ) != len(set(invalidation_codes)):
            raise ValueError("invalidation rules must be unique and ordered")
        if any(item.metric_code not in set(metric_codes) for item in self.invalidation_rules):
            raise ValueError("invalidation rule references an unknown metric")
        if self.invalidation_applicability is InvalidationApplicability.APPLICABLE:
            if not self.invalidation_rules or self.invalidation_not_applicable_reason:
                raise ValueError("applicable invalidation policy requires non-empty rules")
        elif self.invalidation_applicability is InvalidationApplicability.NOT_APPLICABLE:
            if self.invalidation_rules:
                raise ValueError("non-applicable invalidation policy cannot carry rules")
            _require_text(
                self.invalidation_not_applicable_reason,
                "invalidation_not_applicable_reason",
            )
        else:
            raise ValueError("invalidation applicability is invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("baseline spec must remain research-only")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash != _hash_payload(_spec_payload_from_domain(self)):
            raise ValueError("forecast baseline spec content hash mismatch")


def _spec_payload_from_domain(spec: ForecastBaselineSpec) -> dict[str, object]:
    return _spec_payload(
        spec_id=spec.spec_id,
        spec_version=spec.spec_version,
        owner=spec.owner,
        approval_evidence_id=spec.approval_evidence_id,
        approval_evidence_version=spec.approval_evidence_version,
        approval_evidence_content_hash=spec.approval_evidence_content_hash,
        approval_owner=spec.approval_owner,
        approval_status=spec.approval_status,
        evaluation_policy=spec.evaluation_policy,
        subject_code=spec.subject_code,
        industry_code=spec.industry_code,
        candidate_scenario=spec.candidate_scenario,
        horizon_quarters=spec.horizon_quarters,
        family=spec.family,
        computation_method=spec.computation_method,
        computation_code_version=spec.computation_code_version,
        family_parameter_version=spec.family_parameter_version,
        family_parameter_hash=spec.family_parameter_hash,
        seasonal_lag_periods=spec.seasonal_lag_periods,
        pit_inputs=spec.pit_inputs,
        training_window_start=spec.training_window_start,
        training_window_end=spec.training_window_end,
        expected_period_ends=spec.expected_period_ends,
        calendar_schedule=spec.calendar_schedule,
        period_horizons=spec.period_horizons,
        metric_rules=spec.metric_rules,
        metric_evaluation_order=spec.metric_evaluation_order,
        tie_break_rule=spec.tie_break_rule,
        cost_rule=spec.cost_rule,
        invalidation_applicability=spec.invalidation_applicability,
        invalidation_rules=spec.invalidation_rules,
        invalidation_not_applicable_reason=spec.invalidation_not_applicable_reason,
        approved_at=spec.approved_at,
        approval_recorded_at=spec.approval_recorded_at,
        valid_until=spec.valid_until,
    )


def _spec_payload(
    *,
    spec_id: str,
    spec_version: str,
    owner: str,
    approval_evidence_id: str,
    approval_evidence_version: str,
    approval_evidence_content_hash: str,
    approval_owner: str,
    approval_status: BaselineApprovalStatus,
    evaluation_policy: ForecastEvaluationPolicy,
    subject_code: str,
    industry_code: str,
    candidate_scenario: ForecastScenario,
    horizon_quarters: int,
    family: BaselineFamily,
    computation_method: BaselineComputationMethod,
    computation_code_version: str,
    family_parameter_version: str,
    family_parameter_hash: str,
    seasonal_lag_periods: int | None,
    pit_inputs: tuple[BaselinePITInputSpec, ...],
    training_window_start: date,
    training_window_end: date,
    expected_period_ends: tuple[date, ...],
    calendar_schedule: ForecastCalendarScheduleEvidence,
    period_horizons: tuple[ForecastPeriodHorizon, ...],
    metric_rules: tuple[BaselineMetricRule, ...],
    metric_evaluation_order: tuple[str, ...],
    tie_break_rule: TieBreakRule,
    cost_rule: BaselineCostRule,
    invalidation_applicability: InvalidationApplicability,
    invalidation_rules: tuple[BaselineInvalidationRule, ...],
    invalidation_not_applicable_reason: str,
    approved_at: datetime,
    approval_recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "r1-forecast-baseline-spec.v4",
        "spec_id": spec_id,
        "spec_version": spec_version,
        "owner": owner,
        "approval": [
            approval_evidence_id,
            approval_evidence_version,
            approval_evidence_content_hash,
            approval_owner,
            approval_status.value,
            _utc_text(approval_recorded_at),
        ],
        "evaluation_policy": [
            evaluation_policy.policy_id,
            evaluation_policy.policy_version,
            evaluation_policy.policy_content_hash,
            evaluation_policy.owner,
            evaluation_policy.actual_dataset,
            evaluation_policy.actual_knowledge_scope,
            evaluation_policy.actual_revision_rule.value,
            evaluation_policy.actual_vintage_rule.value,
            evaluation_policy.forecast_freeze_rule.value,
            _utc_text(evaluation_policy.forecast_knowledge_cutoff_at),
            _utc_text(evaluation_policy.forecast_submission_deadline_at),
            _utc_text(evaluation_policy.valid_until),
        ],
        "scope": {
            "subject_code": subject_code,
            "industry_code": industry_code,
            "candidate_scenario": candidate_scenario.value,
            "horizon_quarters": horizon_quarters,
        },
        "family": family.value,
        "computation": [computation_method.value, computation_code_version],
        "family_parameters": [
            family_parameter_version,
            family_parameter_hash,
            seasonal_lag_periods,
        ],
        "pit_inputs": [
            {
                "input_role": item.input_role,
                "dataset": item.dataset,
                "metric_code": item.metric_code,
                "unit": item.unit,
                "pit_manifest_id": item.pit_manifest_id,
                "pit_manifest_version": item.pit_manifest_version,
                "pit_manifest_hash": item.pit_manifest_hash,
                "manifest_semantics": {
                    "as_of_time": _utc_text(item.manifest_as_of_time),
                    "produced_at": _utc_text(item.manifest_produced_at),
                    "knowledge_scope": item.manifest_knowledge_scope,
                    "is_verified": item.manifest_is_verified,
                    "coverage_ratio": _decimal_text(item.manifest_coverage_ratio),
                    "missing_count": item.manifest_missing_count,
                    "estimated_count": item.manifest_estimated_count,
                    "unknown_count": item.manifest_unknown_count,
                    "selected_versions": [
                        list(value.identity_tuple) for value in item.selected_versions
                    ],
                    "selected_versions_hash": item.selected_versions_hash,
                },
                "members": [
                    [
                        member.target_period_end.isoformat(),
                        member.source_period_end.isoformat(),
                        member.metric_code,
                        member.selected_member_id,
                        member.selected_member_version,
                        member.selected_member_content_hash,
                        _decimal_text(member.source_value),
                        member.source_unit,
                        _utc_text(member.source_effective_at),
                        _utc_text(member.source_available_at),
                        [
                            member.source_fact_id,
                            member.source_fact_version,
                            member.source_fact_content_hash,
                        ],
                        [
                            member.vintage_id,
                            member.vintage_version,
                            member.vintage_content_hash,
                        ],
                    ]
                    for member in item.members
                ],
                "calendar_id": item.calendar_id,
                "calendar_version": item.calendar_version,
                "calendar_content_hash": item.calendar_content_hash,
            }
            for item in pit_inputs
        ],
        "training_window": [training_window_start.isoformat(), training_window_end.isoformat()],
        "expected_period_ends": [item.isoformat() for item in expected_period_ends],
        "calendar_schedule": {
            "owner": calendar_schedule.owner,
            "identity": [
                calendar_schedule.calendar_id,
                calendar_schedule.calendar_version,
                calendar_schedule.calendar_content_hash,
            ],
            "periods": [
                [item.period_end.isoformat(), item.ordinal] for item in calendar_schedule.periods
            ],
            "content_hash": calendar_schedule.content_hash,
        },
        "period_horizons": [
            {
                "target_period_end": item.target_period_end.isoformat(),
                "forecast_origin_at": _utc_text(item.forecast_origin_at),
                "origin_period_ordinal": item.origin_period_ordinal,
                "target_period_ordinal": item.target_period_ordinal,
                "horizon_quarters": item.horizon_quarters,
                "calendar": [
                    item.calendar_id,
                    item.calendar_version,
                    item.calendar_content_hash,
                ],
                "schedule_content_hash": item.schedule_content_hash,
            }
            for item in period_horizons
        ],
        "metric_rules": [
            {
                "metric_code": item.metric_code,
                "error_metric": item.error_metric.value,
                "maximum_forecast_error": _decimal_text(item.maximum_forecast_error),
                "minimum_improvement": _decimal_text(item.minimum_improvement),
                "minimum_sample_count": item.minimum_sample_count,
                "minimum_coverage": _decimal_text(item.minimum_coverage),
                "mape_zero_actual_rule": item.mape_zero_actual_rule.value,
            }
            for item in metric_rules
        ],
        "metric_evaluation_order": list(metric_evaluation_order),
        "tie_break_rule": tie_break_rule.value,
        "cost_rule": {
            "applicability": cost_rule.applicability.value,
            "cost_model_version": cost_rule.cost_model_version,
            "cost_model_content_hash": cost_rule.cost_model_content_hash,
            "not_applicable_reason": cost_rule.not_applicable_reason,
        },
        "invalidation_rules": [
            {
                "rule_code": item.rule_code,
                "metric_code": item.metric_code,
                "operator": item.operator.value,
                "threshold": _decimal_text(item.threshold),
                "consecutive_periods": item.consecutive_periods,
            }
            for item in invalidation_rules
        ],
        "invalidation_policy": [
            invalidation_applicability.value,
            invalidation_not_applicable_reason,
        ],
        "approved_at": _utc_text(approved_at),
        "valid_until": _utc_text(valid_until),
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


@dataclass(frozen=True)
class ForecastBaselineArtifact:
    """Immutable baseline predictions bound to one approved spec and forecast bundle."""

    artifact_id: str
    artifact_version: str
    owner: str
    evaluation_policy: ForecastEvaluationPolicy
    subject_code: str
    industry_code: str
    candidate_scenario: ForecastScenario
    horizon_quarters: int
    calendar_schedule: ForecastCalendarScheduleEvidence
    period_horizons: tuple[ForecastPeriodHorizon, ...]
    family: BaselineFamily
    computation_method: BaselineComputationMethod
    computation_code_version: str
    family_parameter_version: str
    family_parameter_hash: str
    seasonal_lag_periods: int | None
    spec_id: str
    spec_version: str
    spec_content_hash: str
    pit_inputs: tuple[BaselinePITInputSpec, ...]
    expected_period_ends: tuple[date, ...]
    metric_codes: tuple[str, ...]
    forecasts: tuple[ForecastArtifactReference, ...]
    predictions: tuple[BaselinePredictionObservation, ...]
    knowledge_as_of: datetime
    produced_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        artifact_version: str,
        owner: str,
        spec: ForecastBaselineSpec,
        forecasts: tuple[ForecastArtifactReference, ...],
        predictions: tuple[BaselinePredictionObservation, ...],
        knowledge_as_of: datetime,
        produced_at: datetime,
        valid_until: datetime,
    ) -> ForecastBaselineArtifact:
        """Seal supplied predictions without creating a baseline value."""

        if not spec.approved_at <= produced_at < spec.valid_until or valid_until > spec.valid_until:
            raise ValueError("baseline artifact cannot use an inactive approved spec")
        if spec.cost_rule.applicability is CostApplicability.APPLICABLE:
            raise ValueError("applicable cost rule requires executed cost evidence")

        ordered_forecasts = tuple(sorted(forecasts, key=lambda item: item.target_period_end))
        ordered_predictions = tuple(
            sorted(predictions, key=lambda item: (item.period_end, item.metric_code))
        )
        metric_codes = tuple(item.metric_code for item in spec.metric_rules)
        expected_scope = (
            spec.subject_code,
            spec.industry_code,
            spec.candidate_scenario,
        )
        horizon_by_target = {item.target_period_end: item for item in spec.period_horizons}
        for forecast in ordered_forecasts:
            if (
                forecast.subject_code,
                forecast.industry_code,
                forecast.candidate_scenario,
            ) != expected_scope:
                raise ValueError("forecast reference scope does not match baseline spec")
            if forecast.period_horizon != horizon_by_target.get(forecast.target_period_end):
                raise ValueError("forecast period horizon does not match baseline spec")
            if not spec.approved_at <= forecast.as_of_time < spec.valid_until:
                raise ValueError("forecast reference predates approval or is expired")
            if tuple(item[0] for item in forecast.metric_values) != metric_codes:
                raise ValueError("forecast reference must cover every registered metric")
        content_hash = _hash_payload(
            _artifact_payload(
                artifact_id=artifact_id,
                artifact_version=artifact_version,
                owner=owner,
                evaluation_policy=spec.evaluation_policy,
                subject_code=spec.subject_code,
                industry_code=spec.industry_code,
                candidate_scenario=spec.candidate_scenario,
                horizon_quarters=spec.horizon_quarters,
                calendar_schedule=spec.calendar_schedule,
                period_horizons=spec.period_horizons,
                family=spec.family,
                computation_method=spec.computation_method,
                computation_code_version=spec.computation_code_version,
                family_parameter_version=spec.family_parameter_version,
                family_parameter_hash=spec.family_parameter_hash,
                seasonal_lag_periods=spec.seasonal_lag_periods,
                spec_id=spec.spec_id,
                spec_version=spec.spec_version,
                spec_content_hash=spec.content_hash,
                pit_inputs=spec.pit_inputs,
                expected_period_ends=spec.expected_period_ends,
                metric_codes=metric_codes,
                forecasts=ordered_forecasts,
                predictions=ordered_predictions,
                knowledge_as_of=knowledge_as_of,
                produced_at=produced_at,
                valid_until=valid_until,
            )
        )
        return cls(
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            owner=owner,
            evaluation_policy=spec.evaluation_policy,
            subject_code=spec.subject_code,
            industry_code=spec.industry_code,
            candidate_scenario=spec.candidate_scenario,
            horizon_quarters=spec.horizon_quarters,
            calendar_schedule=spec.calendar_schedule,
            period_horizons=spec.period_horizons,
            family=spec.family,
            computation_method=spec.computation_method,
            computation_code_version=spec.computation_code_version,
            family_parameter_version=spec.family_parameter_version,
            family_parameter_hash=spec.family_parameter_hash,
            seasonal_lag_periods=spec.seasonal_lag_periods,
            spec_id=spec.spec_id,
            spec_version=spec.spec_version,
            spec_content_hash=spec.content_hash,
            pit_inputs=spec.pit_inputs,
            expected_period_ends=spec.expected_period_ends,
            metric_codes=metric_codes,
            forecasts=ordered_forecasts,
            predictions=ordered_predictions,
            knowledge_as_of=knowledge_as_of,
            produced_at=produced_at,
            valid_until=valid_until,
            content_hash=content_hash,
        )

    def __post_init__(self) -> None:
        _require_token(self.artifact_id, "artifact_id")
        _require_token(self.artifact_version, "artifact_version")
        if self.owner != "equity":
            raise ValueError("forecast baseline artifact owner must be equity")
        if any(
            item.as_of_time != self.evaluation_policy.forecast_knowledge_cutoff_at
            or item.persisted_at > self.evaluation_policy.forecast_submission_deadline_at
            for item in self.forecasts
        ):
            raise ValueError("forecast reference violates the approved freeze policy")
        _require_token(self.subject_code, "artifact subject_code")
        _require_token(self.industry_code, "artifact industry_code")
        if not isinstance(self.candidate_scenario, ForecastScenario):
            raise ValueError("artifact candidate_scenario must be a ForecastScenario")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("artifact horizon_quarters must be positive")
        if self.family not in {
            BaselineFamily.SEASONAL_NAIVE,
            BaselineFamily.EXTERNAL_CONSENSUS,
        }:
            raise ValueError("artifact baseline family is not implemented")
        if self.computation_method is not BaselineComputationMethod.DIRECT_APPROVED_SOURCE:
            raise ValueError("artifact computation method is not implemented")
        _require_token(
            self.computation_code_version,
            "artifact computation_code_version",
        )
        _require_token(
            self.family_parameter_version,
            "artifact family_parameter_version",
        )
        _require_sha256(
            self.family_parameter_hash,
            "artifact family_parameter_hash",
        )
        if self.family is BaselineFamily.SEASONAL_NAIVE:
            if (
                isinstance(self.seasonal_lag_periods, bool)
                or self.seasonal_lag_periods is None
                or self.seasonal_lag_periods < 1
            ):
                raise ValueError("seasonal artifact requires an approved positive lag")
        elif self.seasonal_lag_periods is not None:
            raise ValueError("non-seasonal artifact cannot carry a seasonal lag")
        _require_token(self.spec_id, "artifact spec_id")
        _require_token(self.spec_version, "artifact spec_version")
        _require_sha256(self.spec_content_hash, "artifact spec_content_hash")
        _require_aware(self.knowledge_as_of, "artifact knowledge_as_of")
        _require_aware(self.produced_at, "artifact produced_at")
        _require_aware(self.valid_until, "artifact valid_until")
        if not self.knowledge_as_of <= self.produced_at < self.valid_until:
            raise ValueError("baseline artifact time window is invalid")
        periods = tuple(item.target_period_end for item in self.forecasts)
        if periods != self.expected_period_ends or len(periods) != len(set(periods)):
            raise ValueError("forecast references must cover the exact evaluation periods")
        if (
            tuple(item.target_period_end for item in self.period_horizons) != periods
            or max(item.horizon_quarters for item in self.period_horizons) != self.horizon_quarters
        ):
            raise ValueError("artifact period horizons must cover the declared horizon")
        if self.period_horizons != tuple(
            ForecastPeriodHorizon.create(
                target_period_end=item.target_period_end,
                forecast_origin_at=item.forecast_origin_at,
                schedule=self.calendar_schedule,
            )
            for item in self.period_horizons
        ):
            raise ValueError("artifact horizons must derive from its calendar schedule")
        prediction_keys = tuple((item.period_end, item.metric_code) for item in self.predictions)
        expected_keys = tuple(
            (period, metric) for period in self.expected_period_ends for metric in self.metric_codes
        )
        if prediction_keys != expected_keys:
            raise ValueError("baseline predictions require the full period-metric cross-product")
        scope = (
            self.subject_code,
            self.industry_code,
            self.candidate_scenario,
        )
        horizon_by_target = {item.target_period_end: item for item in self.period_horizons}
        if any(
            (
                item.subject_code,
                item.industry_code,
                item.candidate_scenario,
            )
            != scope
            or item.period_horizon != horizon_by_target.get(item.target_period_end)
            for item in self.forecasts
        ):
            raise ValueError("forecast reference scope or horizon does not match artifact")
        if any(
            tuple(item[0] for item in forecast.metric_values) != self.metric_codes
            for forecast in self.forecasts
        ):
            raise ValueError("forecast reference metrics do not match artifact metrics")
        pit_by_role = {item.input_role: item for item in self.pit_inputs}
        for prediction in self.predictions:
            pit_input = pit_by_role.get(prediction.input_role)
            selected_member = (
                next(
                    (
                        member
                        for member in pit_input.members
                        if member.target_period_end == prediction.period_end
                        and member.metric_code == prediction.metric_code
                    ),
                    None,
                )
                if pit_input is not None
                else None
            )
            if pit_input is None or (
                prediction.metric_code != pit_input.metric_code
                or prediction.unit != pit_input.unit
                or prediction.pit_manifest_id != pit_input.pit_manifest_id
                or prediction.pit_manifest_hash != pit_input.pit_manifest_hash
                or selected_member is None
                or prediction.selected_member_id != selected_member.selected_member_id
                or prediction.selected_member_version != selected_member.selected_member_version
                or prediction.selected_member_content_hash
                != selected_member.selected_member_content_hash
                or prediction.computation_evidence.family != self.family
                or prediction.computation_evidence.method != self.computation_method
                or prediction.computation_evidence.code_version != self.computation_code_version
                or prediction.computation_evidence.family_parameter_version
                != self.family_parameter_version
                or prediction.computation_evidence.family_parameter_hash
                != self.family_parameter_hash
                or prediction.computation_evidence.seasonal_lag_periods != self.seasonal_lag_periods
                or prediction.computation_evidence.source_value != selected_member.source_value
                or prediction.computation_evidence.source_unit != selected_member.source_unit
                or prediction.source_fact_id != selected_member.source_fact_id
                or prediction.source_fact_version != selected_member.source_fact_version
                or prediction.source_fact_content_hash != selected_member.source_fact_content_hash
                or prediction.vintage_id != selected_member.vintage_id
                or prediction.vintage_version != selected_member.vintage_version
                or prediction.vintage_content_hash != selected_member.vintage_content_hash
                or prediction.effective_at != selected_member.source_effective_at
                or prediction.available_at != selected_member.source_available_at
            ):
                raise ValueError("baseline prediction source is not a selected PIT member")
        if any(item.available_at > self.knowledge_as_of for item in self.predictions):
            raise ValueError("baseline artifact contains future-unavailable source evidence")
        forecast_by_period = {item.target_period_end: item for item in self.forecasts}
        if any(item.as_of_time > self.knowledge_as_of for item in self.forecasts):
            raise ValueError("artifact knowledge cutoff predates a forecast reference")
        if any(item.persisted_at > self.knowledge_as_of for item in self.forecasts):
            raise ValueError("artifact knowledge cutoff predates forecast persistence")
        if any(
            item.available_at > forecast_by_period[item.period_end].as_of_time
            for item in self.predictions
        ):
            raise ValueError("baseline prediction was unavailable at forecast creation time")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("baseline artifact must remain research-only")
        _require_sha256(self.content_hash, "artifact content_hash")
        payload = _artifact_payload(
            artifact_id=self.artifact_id,
            artifact_version=self.artifact_version,
            owner=self.owner,
            evaluation_policy=self.evaluation_policy,
            subject_code=self.subject_code,
            industry_code=self.industry_code,
            candidate_scenario=self.candidate_scenario,
            horizon_quarters=self.horizon_quarters,
            calendar_schedule=self.calendar_schedule,
            period_horizons=self.period_horizons,
            family=self.family,
            computation_method=self.computation_method,
            computation_code_version=self.computation_code_version,
            family_parameter_version=self.family_parameter_version,
            family_parameter_hash=self.family_parameter_hash,
            seasonal_lag_periods=self.seasonal_lag_periods,
            spec_id=self.spec_id,
            spec_version=self.spec_version,
            spec_content_hash=self.spec_content_hash,
            pit_inputs=self.pit_inputs,
            expected_period_ends=self.expected_period_ends,
            metric_codes=self.metric_codes,
            forecasts=self.forecasts,
            predictions=self.predictions,
            knowledge_as_of=self.knowledge_as_of,
            produced_at=self.produced_at,
            valid_until=self.valid_until,
        )
        if self.content_hash != _hash_payload(payload):
            raise ValueError("forecast baseline artifact content hash mismatch")


def _artifact_payload(
    *,
    artifact_id: str,
    artifact_version: str,
    owner: str,
    evaluation_policy: ForecastEvaluationPolicy,
    subject_code: str,
    industry_code: str,
    candidate_scenario: ForecastScenario,
    horizon_quarters: int,
    calendar_schedule: ForecastCalendarScheduleEvidence,
    period_horizons: tuple[ForecastPeriodHorizon, ...],
    family: BaselineFamily,
    computation_method: BaselineComputationMethod,
    computation_code_version: str,
    family_parameter_version: str,
    family_parameter_hash: str,
    seasonal_lag_periods: int | None,
    spec_id: str,
    spec_version: str,
    spec_content_hash: str,
    pit_inputs: tuple[BaselinePITInputSpec, ...],
    expected_period_ends: tuple[date, ...],
    metric_codes: tuple[str, ...],
    forecasts: tuple[ForecastArtifactReference, ...],
    predictions: tuple[BaselinePredictionObservation, ...],
    knowledge_as_of: datetime,
    produced_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "r1-forecast-baseline-artifact.v4",
        "artifact_id": artifact_id,
        "artifact_version": artifact_version,
        "owner": owner,
        "evaluation_policy_hash": evaluation_policy.policy_content_hash,
        "scope": [
            subject_code,
            industry_code,
            candidate_scenario.value,
            horizon_quarters,
        ],
        "period_horizons": [
            [
                item.target_period_end.isoformat(),
                _utc_text(item.forecast_origin_at),
                item.origin_period_ordinal,
                item.target_period_ordinal,
                item.horizon_quarters,
                item.calendar_id,
                item.calendar_version,
                item.calendar_content_hash,
                item.schedule_content_hash,
            ]
            for item in period_horizons
        ],
        "calendar_schedule_hash": calendar_schedule.content_hash,
        "computation": [
            family.value,
            computation_method.value,
            computation_code_version,
            family_parameter_version,
            family_parameter_hash,
            seasonal_lag_periods,
        ],
        "spec_id": spec_id,
        "spec_version": spec_version,
        "spec_content_hash": spec_content_hash,
        "pit_inputs": [
            {
                "role": item.input_role,
                "dataset": item.dataset,
                "metric": item.metric_code,
                "unit": item.unit,
                "manifest_id": item.pit_manifest_id,
                "manifest_version": item.pit_manifest_version,
                "manifest_hash": item.pit_manifest_hash,
                "manifest_semantics": {
                    "as_of_time": _utc_text(item.manifest_as_of_time),
                    "produced_at": _utc_text(item.manifest_produced_at),
                    "knowledge_scope": item.manifest_knowledge_scope,
                    "is_verified": item.manifest_is_verified,
                    "coverage_ratio": _decimal_text(item.manifest_coverage_ratio),
                    "missing_count": item.manifest_missing_count,
                    "estimated_count": item.manifest_estimated_count,
                    "unknown_count": item.manifest_unknown_count,
                    "selected_versions": [
                        list(value.identity_tuple) for value in item.selected_versions
                    ],
                    "selected_versions_hash": item.selected_versions_hash,
                },
                "members": [
                    [
                        member.target_period_end.isoformat(),
                        member.source_period_end.isoformat(),
                        member.metric_code,
                        member.selected_member_id,
                        member.selected_member_version,
                        member.selected_member_content_hash,
                        _decimal_text(member.source_value),
                        member.source_unit,
                        _utc_text(member.source_effective_at),
                        _utc_text(member.source_available_at),
                        [
                            member.source_fact_id,
                            member.source_fact_version,
                            member.source_fact_content_hash,
                        ],
                        [
                            member.vintage_id,
                            member.vintage_version,
                            member.vintage_content_hash,
                        ],
                    ]
                    for member in item.members
                ],
                "calendar_id": item.calendar_id,
                "calendar_version": item.calendar_version,
                "calendar_hash": item.calendar_content_hash,
            }
            for item in pit_inputs
        ],
        "expected_period_ends": [item.isoformat() for item in expected_period_ends],
        "metric_codes": list(metric_codes),
        "forecasts": [forecast_artifact_reference_payload(item) for item in forecasts],
        "predictions": [
            {
                "period": item.period_end.isoformat(),
                "metric": item.metric_code,
                "input_role": item.input_role,
                "value": _decimal_text(item.value),
                "unit": item.unit,
                "manifest_id": item.pit_manifest_id,
                "manifest_hash": item.pit_manifest_hash,
                "selected_member": [
                    item.selected_member_id,
                    item.selected_member_version,
                    item.selected_member_content_hash,
                ],
                "source_fact": [
                    item.source_fact_id,
                    item.source_fact_version,
                    item.source_fact_content_hash,
                ],
                "computation": {
                    "family": item.computation_evidence.family.value,
                    "method": item.computation_evidence.method.value,
                    "code_version": item.computation_evidence.code_version,
                    "family_parameters": [
                        item.computation_evidence.family_parameter_version,
                        item.computation_evidence.family_parameter_hash,
                        item.computation_evidence.seasonal_lag_periods,
                    ],
                    "source_value": _decimal_text(item.computation_evidence.source_value),
                    "source_unit": item.computation_evidence.source_unit,
                    "source_member": [
                        item.computation_evidence.source_member_id,
                        item.computation_evidence.source_member_version,
                        item.computation_evidence.source_member_content_hash,
                    ],
                    "source_fact": [
                        item.computation_evidence.source_fact_id,
                        item.computation_evidence.source_fact_version,
                        item.computation_evidence.source_fact_content_hash,
                    ],
                    "source_vintage": [
                        item.computation_evidence.source_vintage_id,
                        item.computation_evidence.source_vintage_version,
                        item.computation_evidence.source_vintage_content_hash,
                    ],
                    "hash": item.computation_evidence.computation_hash,
                },
                "effective_at": _utc_text(item.effective_at),
                "available_at": _utc_text(item.available_at),
                "vintage": [
                    item.vintage_id,
                    item.vintage_version,
                    item.vintage_content_hash,
                ],
            }
            for item in predictions
        ],
        "knowledge_as_of": _utc_text(knowledge_as_of),
        "produced_at": _utc_text(produced_at),
        "valid_until": _utc_text(valid_until),
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


__all__ = [
    "BaselineCostRule",
    "BaselineInvalidationRule",
    "BaselineMetricRule",
    "BaselinePredictionObservation",
    "ForecastArtifactReference",
    "ForecastBaselineArtifact",
    "ForecastBaselineSpec",
]
