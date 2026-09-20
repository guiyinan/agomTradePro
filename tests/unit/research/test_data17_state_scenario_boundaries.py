"""Behavioral boundary coverage for the DATA-17 Research Domain slices."""

from __future__ import annotations

import hashlib
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from apps.research.domain.advanced_state_model import (
    AdvancedStateMethodology,
)
from apps.research.domain.scenario_probability_calibration import (
    evaluate_scenario_probability_calibration,
)
from apps.research.domain.scenario_probability_contracts import (
    CalibrationBinResult,
    CalibrationBlocker,
    ForecastLedgerOutcomeObservation,
    MulticlassCalibrationMetrics,
    ProbabilitySourceCalibrationReport,
    ResearchEvidenceStatus,
    RevisionCalibrationMetrics,
    ScenarioInvalidationEvidence,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
    probability_source_calibration_hash,
)
from apps.research.domain.state_model_baseline import (
    BaselineEvaluationEvidence,
    BaselineEvaluationSpecification,
    BaselineEvidenceState,
    BaselineMetricCriterion,
    BaselineMetricObservation,
    BaselineShortfallBlocker,
    BaselineShortfallDecision,
    BaselineShortfallReport,
    ShortfallDirection,
    baseline_shortfall_report_hash,
    evaluate_baseline_shortfall,
)
from apps.research.domain.state_model_qualification_contracts import (
    ComparativeMetricResult,
    StateModelQualificationBlockerCode,
    StateModelQualificationStatus,
)
from apps.research.domain.state_model_qualification_evaluation import (
    StateModelQualificationAssessment,
    missing_state_model_qualification_assessment,
    restore_state_model_qualification_assessment,
)
from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioProbabilitySource,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    complete_candidate,
    proven_shortfall_report,
)
from tests.unit.research.state_model_qualification_factories import (
    accepted_advanced_assessment,
    complete_derived_metric_bundle,
    complete_qualification_study,
    qualification_policy,
    study_preregistration,
)

SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")
SCENARIO_NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _baseline_spec() -> BaselineEvaluationSpecification:
    return BaselineEvaluationSpecification(
        specification_version="baseline-spec.v1",
        baseline_key="regime.simple",
        baseline_version="baseline-v1",
        pit_manifest_id="pit-baseline-v1",
        window_start=SCENARIO_NOW - timedelta(days=30),
        window_end=SCENARIO_NOW - timedelta(days=1),
        minimum_observations=10,
        criteria=(
            BaselineMetricCriterion(
                "error_rate",
                "ratio",
                ShortfallDirection.ABOVE_MAXIMUM,
                Decimal("0.20"),
            ),
            BaselineMetricCriterion(
                "loss",
                "score",
                ShortfallDirection.BELOW_MINIMUM,
                Decimal("0.70"),
            ),
        ),
        approved_by="research-owner",
        activated_at=SCENARIO_NOW - timedelta(days=5),
        valid_until=SCENARIO_NOW + timedelta(days=5),
    )


def _baseline_evidence(
    *,
    metrics: tuple[BaselineMetricObservation, ...] | None = None,
    observation_count: int = 20,
    state: BaselineEvidenceState = BaselineEvidenceState.VERIFIED,
    valid_until: datetime | None = None,
    evidence_refs: tuple[str, ...] = ("pit://baseline-v1",),
    blocking_reason: str | None = None,
) -> BaselineEvaluationEvidence:
    specification = _baseline_spec()
    return BaselineEvaluationEvidence(
        evaluation_id="evaluation-v1",
        specification_version=specification.specification_version,
        baseline_key=specification.baseline_key,
        baseline_version=specification.baseline_version,
        pit_manifest_id=specification.pit_manifest_id,
        state=state,
        window_start=specification.window_start,
        window_end=specification.window_end,
        observation_count=observation_count,
        evaluated_at=SCENARIO_NOW - timedelta(hours=1),
        valid_until=(
            (valid_until or SCENARIO_NOW + timedelta(days=2))
            if state is BaselineEvidenceState.VERIFIED
            else None
        ),
        metrics=metrics
        or (
            BaselineMetricObservation("error_rate", "ratio", Decimal("0.30")),
            BaselineMetricObservation("loss", "score", Decimal("0.50")),
        ),
        evidence_refs=evidence_refs,
        blocking_reason=blocking_reason,
    )


def _not_proven_shortfall_report() -> BaselineShortfallReport:
    """Build a sealed, valid report whose baseline gate remains fail-closed."""

    proven = proven_shortfall_report()
    decision = BaselineShortfallDecision.NOT_PROVEN
    can_propose = False
    metric_results = tuple((metric_key, False) for metric_key, _ in proven.metric_results)
    blockers = (
        BaselineShortfallBlocker(
            reason_code="baseline.shortfall.not_proven",
            detail="the candidate baseline did not satisfy the registered threshold",
        ),
    )
    content_hash = baseline_shortfall_report_hash(
        specification_version=proven.specification_version,
        evaluation_id=proven.evaluation_id,
        baseline_key=proven.baseline_key,
        baseline_version=proven.baseline_version,
        pit_manifest_id=proven.pit_manifest_id,
        window_start=proven.window_start,
        window_end=proven.window_end,
        observation_count=proven.observation_count,
        metrics=proven.metrics,
        evidence_refs=proven.evidence_refs,
        evidence_evaluated_at=proven.evidence_evaluated_at,
        evidence_valid_until=proven.evidence_valid_until,
        evidence_state=proven.evidence_state,
        decision=decision,
        can_propose_advanced_model_research=can_propose,
        metric_results=metric_results,
        blockers=blockers,
    )
    return BaselineShortfallReport(
        specification_version=proven.specification_version,
        evaluation_id=proven.evaluation_id,
        baseline_key=proven.baseline_key,
        baseline_version=proven.baseline_version,
        pit_manifest_id=proven.pit_manifest_id,
        window_start=proven.window_start,
        window_end=proven.window_end,
        observation_count=proven.observation_count,
        metrics=proven.metrics,
        evidence_refs=proven.evidence_refs,
        evidence_evaluated_at=proven.evidence_evaluated_at,
        evidence_valid_until=proven.evidence_valid_until,
        evidence_state=proven.evidence_state,
        decision=decision,
        can_propose_advanced_model_research=can_propose,
        metric_results=metric_results,
        blockers=blockers,
        content_hash=content_hash,
    )


def test_baseline_specification_rejects_each_structural_boundary() -> None:
    specification = _baseline_spec()
    with pytest.raises(ValueError, match="direction is invalid"):
        replace(specification.criteria[0], direction="above")
    with pytest.raises(ValueError, match="window_end must follow"):
        replace(specification, window_end=specification.window_start)
    with pytest.raises(ValueError, match="valid_until must follow"):
        replace(specification, valid_until=specification.activated_at)
    with pytest.raises(ValueError, match="minimum_observations must be positive"):
        replace(specification, minimum_observations=0)
    with pytest.raises(ValueError, match="requires at least one criterion"):
        replace(specification, criteria=())
    with pytest.raises(ValueError, match="duplicate metric criteria"):
        replace(specification, criteria=(specification.criteria[0], specification.criteria[0]))


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"valid_until": SCENARIO_NOW - timedelta(hours=2)}, "valid_until must follow"),
        ({"window_end": SCENARIO_NOW - timedelta(days=31)}, "window_end must follow"),
        ({"observation_count": True}, "cannot be negative"),
        ({"observation_count": -1}, "cannot be negative"),
        (
            {
                "metrics": (
                    BaselineMetricObservation("error_rate", "ratio", Decimal("0.30")),
                    BaselineMetricObservation("error_rate", "ratio", Decimal("0.30")),
                )
            },
            "duplicate metrics",
        ),
    ),
)
def test_baseline_evidence_rejects_invalid_clock_counts_and_metric_identity(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_baseline_evidence(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"valid_until": None}, "requires valid_until"),
        ({"metrics": ()}, "requires metrics and references"),
        ({"evidence_refs": ()}, "requires metrics and references"),
        ({"evidence_refs": (" ",)}, "references cannot be blank"),
        ({"blocking_reason": "unexpected blocker"}, "cannot contain a blocker"),
    ),
)
def test_verified_baseline_evidence_requires_complete_provenance(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_baseline_evidence(), **changes)


def test_baseline_report_and_primitive_guards_remain_fail_closed() -> None:
    report = proven_shortfall_report()
    with pytest.raises(ValueError, match="window_end must follow"):
        replace(report, window_end=report.window_start)
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(report, observation_count=-1)
    with pytest.raises(ValueError, match="metrics must be non-empty"):
        replace(report, metrics=())
    with pytest.raises(ValueError, match="references cannot be blank"):
        replace(report, evidence_refs=(" ",))
    with pytest.raises(ValueError, match="evidence_state is invalid"):
        replace(report, evidence_state="verified")
    with pytest.raises(ValueError, match="sha256 digest"):
        replace(report, content_hash="bad")

    with pytest.raises(ValueError, match="cannot contain whitespace"):
        replace(_baseline_spec(), approved_by="research owner")
    with pytest.raises(ValueError, match="bounded non-blank string"):
        replace(_baseline_spec(), approved_by="")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_baseline_spec(), window_start=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(_baseline_spec().criteria[0], threshold=Decimal("NaN"))


def test_baseline_evaluation_rejects_future_inactive_and_stale_evidence() -> None:
    with pytest.raises(ValueError, match="evaluated in the future"):
        evaluate_baseline_shortfall(
            specification=_baseline_spec(),
            evidence=replace(_baseline_evidence(), evaluated_at=SCENARIO_NOW + timedelta(hours=1)),
            evaluated_at=SCENARIO_NOW,
        )

    inactive_spec = replace(
        _baseline_spec(),
        activated_at=SCENARIO_NOW + timedelta(days=1),
        valid_until=SCENARIO_NOW + timedelta(days=2),
    )
    inactive = evaluate_baseline_shortfall(
        specification=inactive_spec,
        evidence=_baseline_evidence(),
        evaluated_at=SCENARIO_NOW,
    )
    assert any(item.reason_code.endswith("specification_inactive") for item in inactive.blockers)

    stale = evaluate_baseline_shortfall(
        specification=_baseline_spec(),
        evidence=replace(
            _baseline_evidence(),
            valid_until=SCENARIO_NOW - timedelta(minutes=1),
        ),
        evaluated_at=SCENARIO_NOW,
    )
    assert any(item.reason_code.endswith("evidence.stale") for item in stale.blockers)


def _qualification_assessment_with(
    assessment: StateModelQualificationAssessment,
    **changes: object,
) -> StateModelQualificationAssessment:
    values = {field.name: getattr(assessment, field.name) for field in fields(assessment)}
    values.update(changes)
    return restore_state_model_qualification_assessment(
        status=cast(StateModelQualificationStatus, values["status"]),
        study_id=cast(str, values["study_id"]),
        candidate_id=cast(str | None, values["candidate_id"]),
        candidate_version=cast(str | None, values["candidate_version"]),
        study_hash=cast(str | None, values["study_hash"]),
        preregistration_hash=cast(str | None, values["preregistration_hash"]),
        baseline_shortfall_report_hash=cast(str | None, values["baseline_shortfall_report_hash"]),
        candidate_evidence_hash=cast(str | None, values["candidate_evidence_hash"]),
        advanced_assessment_hash=cast(str | None, values["advanced_assessment_hash"]),
        pit_manifest_canonical_hash=cast(str | None, values["pit_manifest_canonical_hash"]),
        artifact_attestation_hash=cast(str | None, values["artifact_attestation_hash"]),
        advanced_threshold_hash=cast(str | None, values["advanced_threshold_hash"]),
        derived_metric_bundle_hash=cast(str | None, values["derived_metric_bundle_hash"]),
        policy_hash=cast(str | None, values["policy_hash"]),
        assessed_at=cast(datetime, values["assessed_at"]),
        metric_results=cast(tuple[ComparativeMetricResult, ...], values["metric_results"]),
        blockers=cast(tuple[StateModelQualificationBlockerCode, ...], values["blockers"]),
        may_request_promotion_review=cast(bool, values["may_request_promotion_review"]),
        promotion_decision_present=cast(bool, values["promotion_decision_present"]),
        research_only=cast(bool, values["research_only"]),
        must_not_use_for_decision=cast(bool, values["must_not_use_for_decision"]),
        must_not_replace_regime=cast(bool, values["must_not_replace_regime"]),
        content_hash=cast(str, values["content_hash"]),
    )


def test_qualification_assessment_restore_rejects_invalid_status_blockers_references_and_flags() -> (
    None
):
    from apps.research.domain.state_model_qualification import evaluate_state_model_qualification

    study = complete_qualification_study()
    candidate = complete_candidate()
    advanced = accepted_advanced_assessment()
    complete = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=complete_derived_metric_bundle(),
        baseline_shortfall=proven_shortfall_report(),
        preregistration=study_preregistration(),
        study=study,
        policy=qualification_policy(),
        assessed_at=NOW,
    )
    with pytest.raises(ValueError, match="status is invalid"):
        _qualification_assessment_with(complete, status="complete")
    with pytest.raises(ValueError, match="blockers must be unique"):
        _qualification_assessment_with(
            complete,
            blockers=(StateModelQualificationBlockerCode.STUDY_MISSING,) * 2,
        )
    with pytest.raises(ValueError, match="requires exact references"):
        _qualification_assessment_with(complete, candidate_id=None)

    blocked = missing_state_model_qualification_assessment(
        study_id="study-missing",
        assessed_at=NOW,
        blocker=StateModelQualificationBlockerCode.STUDY_MISSING,
    )
    with pytest.raises(ValueError, match="requires blockers"):
        _qualification_assessment_with(blocked, blockers=(), may_request_promotion_review=True)
    with pytest.raises(ValueError, match="cannot authorize"):
        _qualification_assessment_with(blocked, research_only=False)


def test_qualification_evaluation_rejects_timeline_and_binding_edges() -> None:
    from apps.research.domain.state_model_qualification import evaluate_state_model_qualification

    study = complete_qualification_study()
    candidate = complete_candidate()
    advanced = accepted_advanced_assessment()
    baseline = proven_shortfall_report()
    preregistration = study_preregistration()
    bundle = complete_derived_metric_bundle()
    policy = qualification_policy()

    other_methodology = replace(
        preregistration,
        methodology=AdvancedStateMethodology.MARKOV_SWITCHING,
        content_hash="0" * 64,
    )
    other_methodology = replace(
        other_methodology, content_hash=other_methodology.calculated_content_hash
    )
    result = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=baseline,
        preregistration=other_methodology,
        study=study,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH in result.blockers

    future_artifact = replace(candidate.artifact, produced_at=NOW + timedelta(hours=1))
    future_draft = replace(candidate, artifact=future_artifact, evidence_hash="0" * 64)
    future_candidate = replace(future_draft, evidence_hash=future_draft.calculated_evidence_hash)
    result = evaluate_state_model_qualification(
        candidate=future_candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=baseline,
        preregistration=preregistration,
        study=study,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.EVIDENCE_TIMELINE_INVALID in result.blockers


def test_qualification_evaluation_rejects_baseline_policy_and_metric_boundaries() -> None:
    from apps.research.domain.state_model_qualification import evaluate_state_model_qualification
    from apps.research.domain.state_model_qualification_contracts import (
        PolicyCoefficientCriterion,
        PolicyCoefficientSign,
    )

    study = complete_qualification_study()
    candidate = complete_candidate()
    advanced = accepted_advanced_assessment()
    baseline = proven_shortfall_report()
    preregistration = study_preregistration()
    bundle = complete_derived_metric_bundle()
    policy = qualification_policy()

    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(baseline, content_hash="f" * 64)

    not_proven_baseline = _not_proven_shortfall_report()
    result = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=not_proven_baseline,
        preregistration=preregistration,
        study=study,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.BASELINE_SHORTFALL_NOT_PROVEN in result.blockers

    study_missing_metric = replace(study, metrics=study.metrics[:-1])
    result = evaluate_state_model_qualification(
        candidate=None,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=proven_shortfall_report(),
        preregistration=preregistration,
        study=study_missing_metric,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.METRIC_SET_MISMATCH in result.blockers

    wrong_unit = replace(study.metrics[0], unit="percent")
    study_wrong_unit = replace(study, metrics=(wrong_unit, *study.metrics[1:]))
    result = evaluate_state_model_qualification(
        candidate=None,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=proven_shortfall_report(),
        preregistration=preregistration,
        study=study_wrong_unit,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.METRIC_UNIT_MISMATCH in result.blockers

    extra_coefficient = PolicyCoefficientCriterion(
        coefficient_key="extra-lag-2",
        target_code="policy_growth_target",
        lag_periods=2,
        expected_sign=PolicyCoefficientSign.POSITIVE,
        maximum_p_value=Decimal("0.05"),
        minimum_absolute_estimate=Decimal("0.10"),
    )
    policy_draft = replace(
        policy,
        coefficient_criteria=(*policy.coefficient_criteria, extra_coefficient),
        content_hash="0" * 64,
    )
    policy_extra = replace(policy_draft, content_hash=policy_draft.calculated_content_hash)
    result = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=proven_shortfall_report(),
        preregistration=preregistration,
        study=study,
        policy=policy_extra,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.POLICY_TARGET_SET_MISMATCH in result.blockers

    low_magnitude = replace(
        study.policy_coefficients[0],
        estimate=Decimal("0.05"),
        confidence_interval_lower=Decimal("0.01"),
        confidence_interval_upper=Decimal("0.10"),
    )
    low_magnitude_study = replace(study, policy_coefficients=(low_magnitude,))
    result = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=proven_shortfall_report(),
        preregistration=preregistration,
        study=low_magnitude_study,
        policy=policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.POLICY_COEFFICIENT_MAGNITUDE_FAILED in result.blockers

    high_sample_policy = replace(
        policy,
        minimum_policy_sample_count=study.sample_count + 1,
        content_hash="0" * 64,
    )
    high_sample_policy = replace(
        high_sample_policy,
        content_hash=high_sample_policy.calculated_content_hash,
    )
    result = evaluate_state_model_qualification(
        candidate=candidate,
        advanced_assessment=advanced,
        derived_metric_bundle=bundle,
        baseline_shortfall=proven_shortfall_report(),
        preregistration=preregistration,
        study=study,
        policy=high_sample_policy,
        assessed_at=NOW,
    )
    assert StateModelQualificationBlockerCode.POLICY_SAMPLE_INSUFFICIENT in result.blockers


def _scope(
    *,
    scenario_set_revision_id: UUID | None = SET_REVISION,
    scenario_revision_ids: tuple[UUID, ...] = (REVISION_B, REVISION_A),
    forecast_horizon: timedelta = timedelta(days=1),
    censoring_rule_version: str = "scenario-censoring.v1",
    path_horizon_periods: int = 2,
    path_initial_state_revision_ids: tuple[UUID, ...] = (REVISION_A, REVISION_B),
) -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=scenario_set_revision_id,
        scenario_revision_ids=scenario_revision_ids,
        forecast_horizon=forecast_horizon,
        censoring_rule_version=censoring_rule_version,
        path_horizon_periods=path_horizon_periods,
        path_initial_state_revision_ids=path_initial_state_revision_ids,
    )


def _policy(
    *,
    forecast_horizon: timedelta = timedelta(days=1),
    censoring_lag: timedelta = timedelta(days=7),
    censoring_rule_version: str = "scenario-censoring.v1",
    path_horizon_periods: int = 2,
    require_all_path_initial_states: bool = True,
    sample_window_start: datetime = datetime(2026, 8, 1, tzinfo=UTC),
    sample_window_end: datetime = datetime(2026, 8, 4, tzinfo=UTC),
    minimum_forecasts: int = 2,
    minimum_resolved: int = 2,
    minimum_coverage: Decimal = Decimal("1"),
    minimum_binary_class: int = 1,
    minimum_multiclass_groups: int = 2,
    minimum_multiclass_class: int = 1,
    activated_at: datetime = SCENARIO_NOW - timedelta(days=30),
    valid_until: datetime = SCENARIO_NOW + timedelta(days=30),
) -> ScenarioProbabilityResearchPolicy:
    return ScenarioProbabilityResearchPolicy.create(
        policy_version="scenario-calibration-policy.v1",
        activated_at=activated_at,
        valid_until=valid_until,
        sample_window_start=sample_window_start,
        sample_window_end=sample_window_end,
        forecast_horizon=forecast_horizon,
        censoring_lag=censoring_lag,
        censoring_rule_version=censoring_rule_version,
        minimum_forecasts_per_revision=minimum_forecasts,
        minimum_resolved_outcomes_per_revision=minimum_resolved,
        minimum_outcome_coverage=minimum_coverage,
        minimum_binary_class_observations=minimum_binary_class,
        minimum_multiclass_groups=minimum_multiclass_groups,
        minimum_multiclass_class_observations=minimum_multiclass_class,
        maximum_outcome_evidence_age=timedelta(days=365),
        calibration_bin_edges=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=2,
        minimum_path_probability_observations=10,
        path_horizon_periods=path_horizon_periods,
        require_all_path_initial_states=require_all_path_initial_states,
        maximum_research_evidence_age=timedelta(days=90),
        invalidation_review_delay=timedelta(days=1),
        approved_by="research-owner",
    )


def _observation(
    *,
    entry_id: str,
    group_id: str,
    revision_id: UUID,
    subjective_probability: str,
    scenario_realized: bool | None,
    published_at: datetime,
    model_probability: str | None = None,
    subjective_version: str = "committee-v1",
    model_version: str = "promoted-model-v1",
    promotion_id: str = "promotion-model-v1",
    set_revision: UUID | None = SET_REVISION,
    censoring_rule_version: str = "scenario-censoring.v1",
    horizon: timedelta = timedelta(days=1),
    outcome_recorded_at: datetime | None = None,
    outcome_valid_until: datetime | None = None,
    invalidation: ScenarioInvalidationEvidence | None = None,
    auto_complete_outcome: bool = True,
) -> ForecastLedgerOutcomeObservation:
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=revision_id,
        scenario_set_revision_id=set_revision,
        subjective_probability=subjective_probability,
        subjective_probability_source_version=subjective_version,
        model_probability=model_probability,
        model_probability_source_version=model_version if model_probability is not None else None,
        model_promotion_decision_id=promotion_id if model_probability is not None else None,
    )
    horizon_end = published_at + horizon
    if auto_complete_outcome and scenario_realized is not None and outcome_recorded_at is None:
        outcome_recorded_at = horizon_end + timedelta(hours=1)
    if auto_complete_outcome and scenario_realized is not None and outcome_valid_until is None:
        outcome_valid_until = SCENARIO_NOW + timedelta(days=30)
    return ForecastLedgerOutcomeObservation.create(
        observation_version="ledger-observation.v1",
        entry_id=entry_id,
        forecast_group_id=group_id,
        binding=binding,
        pit_manifest_id=f"pit-{group_id}",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash=hashlib.sha256(f"pit-{group_id}".encode()).hexdigest(),
        censoring_rule_version=censoring_rule_version,
        published_at=published_at,
        horizon_end=horizon_end,
        scenario_realized=scenario_realized,
        outcome_recorded_at=outcome_recorded_at,
        outcome_evidence_valid_until=outcome_valid_until,
        invalidation=invalidation,
    )


def _complete_observations(
    *, include_model: bool = False
) -> tuple[ForecastLedgerOutcomeObservation, ...]:
    model_values = ("0.20", "0.80", "0.80", "0.20") if include_model else (None,) * 4
    return (
        _observation(
            entry_id="g1-a",
            group_id="g1",
            revision_id=REVISION_A,
            subjective_probability="0.70",
            model_probability=model_values[0],
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="g1-b",
            group_id="g1",
            revision_id=REVISION_B,
            subjective_probability="0.30",
            model_probability=model_values[1],
            scenario_realized=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="g2-a",
            group_id="g2",
            revision_id=REVISION_A,
            subjective_probability="0.40",
            model_probability=model_values[2],
            scenario_realized=False,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
        _observation(
            entry_id="g2-b",
            group_id="g2",
            revision_id=REVISION_B,
            subjective_probability="0.60",
            model_probability=model_values[3],
            scenario_realized=True,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
    )


def test_scenario_scope_rejects_singleton_set_and_membership_hash_edges() -> None:
    with pytest.raises(ValueError, match="exactly one revision"):
        _scope(scenario_set_revision_id=None)
    with pytest.raises(ValueError, match="at least two revisions"):
        _scope(scenario_revision_ids=(REVISION_A,))
    with pytest.raises(ValueError, match="path initial states must belong"):
        _scope(path_initial_state_revision_ids=(UUID("00000000-0000-0000-0000-000000000999"),))
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(_scope(), content_hash="a" * 64)


def test_scenario_policy_rejects_each_zero_or_reversed_threshold() -> None:
    cases = (
        ("valid_until", _policy().activated_at, "valid_until must follow"),
        ("sample_window_end", _policy().sample_window_start, "sample_window_end must follow"),
        ("forecast_horizon", timedelta(0), "forecast_horizon must be positive"),
        ("censoring_lag", timedelta(days=-1), "censoring_lag cannot be negative"),
        ("minimum_forecasts_per_revision", 0, "must be a positive integer"),
        ("minimum_outcome_coverage", Decimal(0), "coverage must be greater"),
        ("probability_sum_tolerance", Decimal(0), "tolerance must be greater"),
        ("maximum_outcome_evidence_age", timedelta(0), "must be positive"),
        ("invalidation_review_delay", timedelta(days=-1), "cannot be negative"),
    )
    for field_name, value, message in cases:
        policy = _policy()
        with pytest.raises(ValueError, match=message):
            replace(policy, **{field_name: value})
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(_policy(), content_hash="a" * 64)


def test_scenario_invalidation_and_ledger_outcome_contracts_reject_partial_graphs() -> None:
    with pytest.raises(ValueError, match="requires evidence references"):
        ScenarioInvalidationEvidence.create(
            evidence_version="invalidation.v1",
            scenario_revision_id=REVISION_A,
            scenario_set_revision_id=SET_REVISION,
            invalidated_at=SCENARIO_NOW,
            invalidation_rule_version="rule.v1",
            pit_manifest_id="pit-g1",
            evidence_refs=(),
        )
    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="invalidation.v1",
        scenario_revision_id=REVISION_A,
        scenario_set_revision_id=SET_REVISION,
        invalidated_at=SCENARIO_NOW,
        invalidation_rule_version="rule.v1",
        pit_manifest_id="pit-g1",
        evidence_refs=("research://invalidation",),
    )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(invalidation, content_hash="a" * 64)

    published = datetime(2026, 8, 1, tzinfo=UTC)
    base = {
        "entry_id": "ledger-edge",
        "group_id": "ledger-edge",
        "revision_id": REVISION_A,
        "subjective_probability": "0.5",
        "published_at": published,
    }
    with pytest.raises(ValueError, match="horizon_end must follow"):
        _observation(**base, scenario_realized=None, horizon=timedelta(0))
    with pytest.raises(ValueError, match="outcome fields must be complete"):
        _observation(
            **base,
            scenario_realized=True,
            outcome_recorded_at=None,
            outcome_valid_until=None,
            auto_complete_outcome=False,
        )
    with pytest.raises(ValueError, match="scenario_realized must be boolean"):
        _observation(
            **base,
            scenario_realized=cast(bool | None, 1),
            outcome_recorded_at=published + timedelta(days=1, hours=1),
            outcome_valid_until=published + timedelta(days=2),
        )
    with pytest.raises(ValueError, match="cannot precede horizon_end"):
        _observation(
            **base,
            scenario_realized=True,
            outcome_recorded_at=published + timedelta(hours=1),
            outcome_valid_until=published + timedelta(days=2),
        )
    with pytest.raises(ValueError, match="validity must follow recording"):
        _observation(
            **base,
            scenario_realized=True,
            outcome_recorded_at=published + timedelta(days=1, hours=1),
            outcome_valid_until=published + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="invalidated scenario"):
        _observation(**base, scenario_realized=True, invalidation=invalidation)
    mismatched_invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="invalidation.v1",
        scenario_revision_id=REVISION_B,
        scenario_set_revision_id=SET_REVISION,
        invalidated_at=SCENARIO_NOW,
        invalidation_rule_version="rule.v1",
        pit_manifest_id="pit-g1",
        evidence_refs=("research://invalidation",),
    )
    with pytest.raises(ValueError, match="does not match ledger"):
        _observation(
            **base,
            scenario_realized=None,
            invalidation=mismatched_invalidation,
        )
    early_invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="invalidation.v1",
        scenario_revision_id=REVISION_A,
        scenario_set_revision_id=SET_REVISION,
        invalidated_at=published - timedelta(seconds=1),
        invalidation_rule_version="rule.v1",
        pit_manifest_id="pit-g1",
        evidence_refs=("research://invalidation",),
    )
    with pytest.raises(ValueError, match="cannot precede forecast publication"):
        _observation(
            **base,
            scenario_realized=None,
            invalidation=early_invalidation,
        )


def _source_report(
    *,
    source: ScenarioProbabilitySource,
    status: ResearchEvidenceStatus,
    revision_metrics: tuple[RevisionCalibrationMetrics, ...] = (),
    multiclass_metrics: MulticlassCalibrationMetrics | None = None,
    blockers: tuple[CalibrationBlocker, ...] = (),
) -> ProbabilitySourceCalibrationReport:
    report_version = "scenario-source-calibration.v1"
    policy_version = "scenario-calibration-policy.v1"
    scope_hash = _scope().content_hash
    content_hash = probability_source_calibration_hash(
        report_version=report_version,
        source=source,
        policy_version=policy_version,
        scope_hash=scope_hash,
        evaluated_at=SCENARIO_NOW,
        status=status,
        revision_metrics=revision_metrics,
        multiclass_metrics=multiclass_metrics,
        blockers=blockers,
    )
    return ProbabilitySourceCalibrationReport(
        report_version=report_version,
        probability_source=source,
        policy_version=policy_version,
        scope_hash=scope_hash,
        evaluated_at=SCENARIO_NOW,
        status=status,
        revision_metrics=revision_metrics,
        multiclass_metrics=multiclass_metrics,
        blockers=blockers,
        content_hash=content_hash,
    )


def test_source_and_combined_calibration_reports_reject_publication_shape_drift() -> None:
    with pytest.raises(ValueError, match="requires metrics"):
        _source_report(
            source=ScenarioProbabilitySource.SUBJECTIVE, status=ResearchEvidenceStatus.AVAILABLE
        )
    dummy_metrics = RevisionCalibrationMetrics(
        scenario_revision_id=REVISION_A,
        probability_source_version="v1",
        forecast_count=1,
        resolved_outcome_count=1,
        outcome_coverage=Decimal("1"),
        realized_count=1,
        not_realized_count=0,
        mean_brier_score=Decimal("0"),
        bins=(
            CalibrationBinResult(
                lower_bound=Decimal("0"),
                upper_bound=Decimal("1"),
                sample_count=1,
                mean_forecast_probability=Decimal("1"),
                observed_hit_rate=Decimal("1"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="cannot publish partial"):
        _source_report(
            source=ScenarioProbabilitySource.SUBJECTIVE,
            status=ResearchEvidenceStatus.BLOCKED,
            revision_metrics=(dummy_metrics,),
        )
    with pytest.raises(ValueError, match="requires blockers"):
        _source_report(
            source=ScenarioProbabilitySource.SUBJECTIVE,
            status=ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE,
        )

    complete = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=_complete_observations(include_model=True),
        evaluated_at=SCENARIO_NOW,
    )
    with pytest.raises(ValueError, match="subjective source"):
        replace(complete, subjective=complete.model_inferred, content_hash="a" * 64)
    with pytest.raises(ValueError, match="model_inferred source"):
        replace(complete, model_inferred=complete.subjective, content_hash="a" * 64)
    mismatched_subjective = replace(
        complete.subjective,
        policy_version="other-policy",
        content_hash=probability_source_calibration_hash(
            report_version=complete.subjective.report_version,
            source=complete.subjective.probability_source,
            policy_version="other-policy",
            scope_hash=complete.subjective.scope_hash,
            evaluated_at=complete.subjective.evaluated_at,
            status=complete.subjective.status,
            revision_metrics=complete.subjective.revision_metrics,
            multiclass_metrics=complete.subjective.multiclass_metrics,
            blockers=complete.subjective.blockers,
        ),
    )
    with pytest.raises(ValueError, match="identity does not match"):
        replace(complete, subjective=mismatched_subjective, content_hash="a" * 64)
    with pytest.raises(ValueError, match="cannot train"):
        replace(complete, trains_probability_model=True, content_hash="a" * 64)
    with pytest.raises(ValueError, match="research-only"):
        replace(complete, research_only=False, content_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(complete, content_hash="a" * 64)


def test_calibration_rejects_source_mixing_and_scope_boundaries() -> None:
    rows = _complete_observations(include_model=True)
    mixed_subjective = (
        _observation(
            entry_id="mixed-a",
            group_id="mixed",
            revision_id=REVISION_A,
            subjective_probability="0.7",
            model_probability="0.2",
            subjective_version="committee-v2",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        rows[1],
        rows[2],
        rows[3],
    )
    mixed_versions = evaluate_scenario_probability_calibration(
        scope=_scope(), policy=_policy(), observations=mixed_subjective, evaluated_at=SCENARIO_NOW
    )
    assert any("version.mixed" in item.reason_code for item in mixed_versions.subjective.blockers)

    mixed_promotions = (
        _observation(
            entry_id="promotion-a",
            group_id="promotion",
            revision_id=REVISION_A,
            subjective_probability="0.7",
            model_probability="0.2",
            promotion_id="promotion-a",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="promotion-b",
            group_id="promotion",
            revision_id=REVISION_B,
            subjective_probability="0.3",
            model_probability="0.8",
            promotion_id="promotion-b",
            scenario_realized=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    mixed_model = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(minimum_forecasts=1, minimum_resolved=1, minimum_multiclass_groups=1),
        observations=mixed_promotions,
        evaluated_at=SCENARIO_NOW,
    )
    assert any(
        "promotion.mixed" in item.reason_code for item in mixed_model.model_inferred.blockers
    )

    singleton = _scope(
        scenario_set_revision_id=None,
        scenario_revision_ids=(REVISION_A,),
        path_initial_state_revision_ids=(REVISION_A,),
    )
    singleton_rows = (
        _observation(
            entry_id="singleton-true",
            group_id="singleton",
            revision_id=REVISION_A,
            set_revision=None,
            subjective_probability="0.2",
            model_probability="0.2",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="singleton-false",
            group_id="singleton",
            revision_id=REVISION_A,
            set_revision=None,
            subjective_probability="0.2",
            model_probability="0.2",
            scenario_realized=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    singleton_report = evaluate_scenario_probability_calibration(
        scope=singleton,
        policy=_policy(minimum_multiclass_groups=1),
        observations=singleton_rows,
        evaluated_at=SCENARIO_NOW,
    )
    assert singleton_report.subjective.status is ResearchEvidenceStatus.AVAILABLE
    assert any(len(metric.bins) == 1 for metric in singleton_report.subjective.revision_metrics)


@pytest.mark.parametrize(
    ("scope_changes", "message"),
    (
        ({"forecast_horizon": timedelta(days=2)}, "forecast horizon"),
        ({"censoring_rule_version": "other-censoring"}, "censoring rule"),
        ({"path_horizon_periods": 3}, "path horizon"),
        (
            {"path_initial_state_revision_ids": (REVISION_A,)},
            "every path initial state",
        ),
    ),
)
def test_calibration_scope_policy_identity_is_exact(
    scope_changes: dict[str, object], message: str
) -> None:
    scope = _scope(**scope_changes)
    with pytest.raises(ValueError, match=message):
        evaluate_scenario_probability_calibration(
            scope=scope,
            policy=_policy(),
            observations=(),
            evaluated_at=SCENARIO_NOW,
        )


@pytest.mark.parametrize(
    "observation",
    (
        _observation(
            entry_id="out-of-scope",
            group_id="edge",
            revision_id=UUID("00000000-0000-0000-0000-000000000999"),
            subjective_probability="0.5",
            scenario_realized=None,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            set_revision=None,
        ),
        _observation(
            entry_id="outside-window",
            group_id="edge",
            revision_id=REVISION_A,
            subjective_probability="0.5",
            scenario_realized=None,
            published_at=datetime(2026, 7, 31, tzinfo=UTC),
            set_revision=None,
        ),
        _observation(
            entry_id="wrong-censoring",
            group_id="edge",
            revision_id=REVISION_A,
            subjective_probability="0.5",
            scenario_realized=None,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            censoring_rule_version="other-censoring",
            set_revision=None,
        ),
    ),
)
def test_calibration_rejects_observation_scope_identity_substitution(
    observation: ForecastLedgerOutcomeObservation,
) -> None:
    message = (
        "out of scope"
        if observation.entry_id == "out-of-scope"
        else (
            "outside the policy sample window"
            if observation.entry_id == "outside-window"
            else "censoring rule mismatch"
        )
    )
    with pytest.raises(ValueError, match=message):
        evaluate_scenario_probability_calibration(
            scope=_scope(
                scenario_set_revision_id=None,
                scenario_revision_ids=(REVISION_A,),
                path_initial_state_revision_ids=(REVISION_A,),
            ),
            policy=_policy(),
            observations=(observation,),
            evaluated_at=SCENARIO_NOW,
        )


def test_calibration_rejects_future_observations_and_exact_censoring_lag() -> None:
    future_published = _observation(
        entry_id="future-published",
        group_id="future",
        revision_id=REVISION_A,
        subjective_probability="0.5",
        scenario_realized=None,
        published_at=datetime(2026, 8, 3, tzinfo=UTC),
        set_revision=None,
    )
    with pytest.raises(ValueError, match="future-dated"):
        evaluate_scenario_probability_calibration(
            scope=_scope(
                scenario_set_revision_id=None,
                scenario_revision_ids=(REVISION_A,),
                path_initial_state_revision_ids=(REVISION_A,),
            ),
            policy=_policy(),
            observations=(future_published,),
            evaluated_at=datetime(2026, 8, 2, tzinfo=UTC),
        )

    future_outcome = _observation(
        entry_id="future-outcome",
        group_id="future-outcome",
        revision_id=REVISION_A,
        subjective_probability="0.5",
        scenario_realized=True,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        set_revision=None,
        outcome_recorded_at=SCENARIO_NOW + timedelta(hours=1),
        outcome_valid_until=SCENARIO_NOW + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="outcome cannot be future"):
        evaluate_scenario_probability_calibration(
            scope=_scope(
                scenario_set_revision_id=None,
                scenario_revision_ids=(REVISION_A,),
                path_initial_state_revision_ids=(REVISION_A,),
            ),
            policy=_policy(),
            observations=(future_outcome,),
            evaluated_at=SCENARIO_NOW,
        )

    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="invalidation.v1",
        scenario_revision_id=REVISION_A,
        scenario_set_revision_id=None,
        invalidated_at=SCENARIO_NOW + timedelta(hours=1),
        invalidation_rule_version="rule.v1",
        pit_manifest_id="pit-future-invalidation",
        evidence_refs=("research://future-invalidation",),
    )
    future_invalidation = _observation(
        entry_id="future-invalidation",
        group_id="future-invalidation",
        revision_id=REVISION_A,
        set_revision=None,
        subjective_probability="0.5",
        scenario_realized=None,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        invalidation=invalidation,
    )
    with pytest.raises(ValueError, match="invalidation cannot be future"):
        evaluate_scenario_probability_calibration(
            scope=_scope(
                scenario_set_revision_id=None,
                scenario_revision_ids=(REVISION_A,),
                path_initial_state_revision_ids=(REVISION_A,),
            ),
            policy=_policy(),
            observations=(future_invalidation,),
            evaluated_at=SCENARIO_NOW,
        )

    uncensored = _observation(
        entry_id="uncensored",
        group_id="uncensored",
        revision_id=REVISION_A,
        set_revision=None,
        subjective_probability="0.5",
        scenario_realized=None,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="censoring lag"):
        evaluate_scenario_probability_calibration(
            scope=_scope(
                scenario_set_revision_id=None,
                scenario_revision_ids=(REVISION_A,),
                path_initial_state_revision_ids=(REVISION_A,),
            ),
            policy=_policy(censoring_lag=timedelta(days=1)),
            observations=(uncensored,),
            evaluated_at=SCENARIO_NOW,
        )


def test_calibration_multiclass_rejects_probability_sum_and_realization_edges() -> None:
    bad_sum = (
        _observation(
            entry_id="sum-a",
            group_id="sum",
            revision_id=REVISION_A,
            subjective_probability="0.9",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="sum-b",
            group_id="sum",
            revision_id=REVISION_B,
            subjective_probability="0.9",
            scenario_realized=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(minimum_forecasts=1, minimum_resolved=1, minimum_multiclass_groups=1),
        observations=bad_sum,
        evaluated_at=SCENARIO_NOW,
    )
    assert any("probability_sum_invalid" in item.reason_code for item in report.subjective.blockers)

    invalid_realization = (
        _observation(
            entry_id="realized-a",
            group_id="realized",
            revision_id=REVISION_A,
            subjective_probability="0.5",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="realized-b",
            group_id="realized",
            revision_id=REVISION_B,
            subjective_probability="0.5",
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(minimum_forecasts=1, minimum_resolved=1, minimum_multiclass_groups=1),
        observations=invalid_realization,
        evaluated_at=SCENARIO_NOW,
    )
    assert any("realization_invalid" in item.reason_code for item in report.subjective.blockers)
