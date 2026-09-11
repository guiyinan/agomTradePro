"""Behavioral boundary tests for Research monitoring Domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r2_market_structure_trial_contracts import (
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExpectedPeriod,
    R2MultipleTestingRule,
    R2ThresholdDirection,
)
from apps.research.domain.r2_market_structure_trial_evaluation import (
    R2AuditExplanatoryOutcome,
    R2ExplanatoryTrialAssessment,
    R2TrialBlockerCode,
    R2TrialStatus,
    evaluate_r2_explanatory_trial,
    evaluate_r2_monitoring,
)
from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationFact,
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
    calculate_r7_brier_score,
    calculate_r7_forecast_outcome_coverage,
    calculate_r7_probability_coverage,
    derive_r7_monitoring_status,
    evaluate_r7_post_promotion_monitoring,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringPredictionMember,
    prediction_member_hash,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    R2SyntheticScenario,
    build_r2_scenario,
    digest,
)
from tests.unit.research.r7_research_result_factories import make_result
from tests.unit.research.test_r7_post_promotion_monitoring import (
    _active_period_and_fact,
    _lifecycle_owner_evidence,
    _promotion_stream,
)


def test_r7_prediction_projection_rejects_tampered_probability_and_types() -> None:
    """Outcome-free prediction projections retain exact types and bounded probabilities."""

    active, _, _, _ = _active_period_and_fact()
    prediction = active.predictions[0]

    with pytest.raises(TypeError, match="exact forecast row"):
        R7MonitoringPredictionMember.from_observation(object())

    with pytest.raises(ValueError, match="version is unsupported"):
        replace(prediction, prediction_version="r7-monitoring-prediction.v2")

    with pytest.raises(TypeError, match="scenario-set revision"):
        replace(prediction, scenario_set_revision_id="not-a-uuid")

    with pytest.raises(ValueError, match="subjective probability"):
        replace(prediction, subjective_probability=Decimal("1.1"))

    with pytest.raises(ValueError, match="projection is incomplete"):
        replace(
            prediction,
            model_probability=Decimal("0.5"),
            model_probability_source_version=None,
            model_promotion_decision_id=None,
        )

    with pytest.raises(ValueError, match="model probability is invalid"):
        replace(
            prediction,
            model_probability=Decimal("1.1"),
            model_probability_source_version="model.v1",
            model_promotion_decision_id="promotion-1",
        )

    with pytest.raises(ValueError, match="horizon is invalid"):
        replace(prediction, horizon_end=prediction.published_at)

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(prediction, content_hash="0" * 64)

    object.__setattr__(prediction, "subjective_probability", object())
    with pytest.raises(ValueError, match="finite Decimal"):
        prediction_member_hash(prediction)


def test_r7_realization_member_rejects_owner_clock_and_outcome_conflicts() -> None:
    """A realization cannot precede its owner outcome or combine resolved and invalidated state."""

    _, _, _, fact = _active_period_and_fact()
    member = fact.members[0]
    observation = next(
        item
        for item in make_result().evidence_graph.forecast_observations
        if item.entry_id == member.entry_id
        and item.outcome_recorded_at is not None
        and item.outcome_recorded_at > item.horizon_end
    )

    with pytest.raises(ValueError, match="predates its owner outcome"):
        R7ForecastRealizationMember.from_owner_observation(
            observation=observation,
            available_at=observation.horizon_end,
            recorded_at=observation.horizon_end + timedelta(minutes=1),
            evidence_ref="signal://r7/early-realization",
        )

    with pytest.raises(ValueError, match="mutually exclusive"):
        replace(member, invalidated=True)

    with pytest.raises(TypeError, match="exact bool"):
        replace(member, realized=1)

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(member, content_hash="0" * 64)


def test_r7_lifecycle_attestation_revalidates_stream_identity_and_clock() -> None:
    """The owner attestation rejects incomplete, substituted, expired, and stale streams."""

    stream = _promotion_stream()
    attestation = _lifecycle_owner_evidence(stream)

    with pytest.raises(ValueError, match="complete stream"):
        R7LifecycleStreamOwnerEvidence.create(
            attestation_id="r7-lifecycle-empty",
            attestation_version=attestation.attestation_version,
            owner="research",
            lifecycle_stream=(),
            recorded_at=attestation.recorded_at,
            valid_until=attestation.valid_until,
            evidence_ref="research://r7/empty",
        )

    with pytest.raises(TypeError, match="invalid event"):
        R7LifecycleStreamOwnerEvidence.create(
            attestation_id="r7-lifecycle-invalid-event",
            attestation_version=attestation.attestation_version,
            owner="research",
            lifecycle_stream=(object(),),
            recorded_at=attestation.recorded_at,
            valid_until=attestation.valid_until,
            evidence_ref="research://r7/invalid-event",
        )

    with pytest.raises(ValueError, match="version is unsupported"):
        replace(attestation, attestation_version="r7-lifecycle-stream-owner-evidence.v2")

    with pytest.raises(ValueError, match="must be research"):
        replace(attestation, owner="signal")

    with pytest.raises(ValueError, match="event count is invalid"):
        replace(attestation, event_count=0)

    with pytest.raises(ValueError, match="already expired"):
        replace(attestation, recorded_at=attestation.valid_until)

    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(attestation, content_hash="0" * 64)

    with pytest.raises(ValueError, match="stream is incomplete"):
        attestation.validate_stream(())

    with pytest.raises(TypeError, match="invalid event"):
        attestation.validate_stream((object(),))

    with pytest.raises(ValueError, match="exact owner attestation"):
        attestation.validate_stream(stream + stream[:1])

    early_attestation = R7LifecycleStreamOwnerEvidence.create(
        attestation_id="r7-lifecycle-early-head",
        attestation_version=attestation.attestation_version,
        owner=attestation.owner,
        lifecycle_stream=stream,
        recorded_at=stream[-1].recorded_at - timedelta(seconds=1),
        valid_until=attestation.valid_until,
        evidence_ref="research://r7/early-head",
    )
    with pytest.raises(ValueError, match="predates its exact head"):
        early_attestation.validate_stream(stream)


def test_r7_owner_fact_and_evaluator_boundaries_fail_closed() -> None:
    """Owner, fact, metric, and assessment boundaries preserve exact evidence semantics."""

    active, calendar, period, fact = _active_period_and_fact()
    owner = fact.owner_record

    with pytest.raises(TypeError, match="owner period type"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="r7-owner-invalid-period",
            owner_record_version=owner.owner_record_version,
            period=object(),
            pit_as_of=owner.pit_as_of,
            available_at=owner.available_at,
            recorded_at=owner.recorded_at,
            valid_until=owner.valid_until,
            evidence_ref="signal://r7/invalid-period",
            members=owner.members,
        )

    with pytest.raises(ValueError, match="requires complete members"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="r7-owner-empty",
            owner_record_version=owner.owner_record_version,
            period=period,
            pit_as_of=owner.pit_as_of,
            available_at=owner.available_at,
            recorded_at=owner.recorded_at,
            valid_until=owner.valid_until,
            evidence_ref="signal://r7/empty-members",
            members=(),
        )

    with pytest.raises(ValueError, match="must be Forecast Ledger"):
        replace(owner, owner="research")

    with pytest.raises(ValueError, match="membership is incomplete"):
        replace(owner, members=())

    with pytest.raises(ValueError, match="payload seal mismatch"):
        replace(owner, payload_hash="0" * 64)

    with pytest.raises(TypeError, match="fact period type"):
        R7ForecastRealizationFact.from_owner_record(period=object(), owner_record=owner)

    with pytest.raises(TypeError, match="fact owner record type"):
        R7ForecastRealizationFact.from_owner_record(period=period, owner_record=object())

    with pytest.raises(ValueError, match="owner period substitution"):
        replace(fact, period_id="r7-substituted-period")

    assessment = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=fact,
        evaluated_at=owner.recorded_at,
        maximum_subjective_brier_score=Decimal("0.2"),
        maximum_model_brier_score=Decimal("0.2"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )

    with pytest.raises(ValueError, match="monitoring subjective_brier_score is invalid"):
        replace(assessment, subjective_brier_score=Decimal("2"))

    with pytest.raises(TypeError, match="blockers are invalid"):
        replace(assessment, blocker_codes=(object(),))

    with pytest.raises(TypeError, match="assessment status is invalid"):
        replace(assessment, status="blocked")

    with pytest.raises(ValueError, match="research-only"):
        replace(assessment, automatic_retirement=True)

    with pytest.raises(ValueError, match="manual-review flag"):
        replace(assessment, manual_retirement_review_required=True)


def test_r7_public_metrics_and_status_inputs_fail_closed() -> None:
    """Metric helpers accept only exact Domain values and exact enum/boolean inputs."""

    active, _, period, fact = _active_period_and_fact()

    with pytest.raises(TypeError, match="active result type"):
        calculate_r7_forecast_outcome_coverage(
            active=object(),
            period=period,
            realization=fact,
        )

    with pytest.raises(TypeError, match="probability source"):
        calculate_r7_probability_coverage(
            active=active,
            period=period,
            realization=fact,
            source=object(),
        )

    with pytest.raises(TypeError, match="probability source"):
        calculate_r7_brier_score(
            active=active,
            period=period,
            realization=fact,
            source=object(),
        )

    with pytest.raises(TypeError, match="blockers are invalid"):
        derive_r7_monitoring_status(
            blocker_codes=(object(),),
            threshold_breached=False,
            falsification_detected=False,
        )

    with pytest.raises(TypeError, match="exact booleans"):
        derive_r7_monitoring_status(
            blocker_codes=(),
            threshold_breached=1,
            falsification_detected=False,
        )


def _evaluate_trial(
    scenario: R2SyntheticScenario,
    *,
    taxonomy_publication: R2CanonicalPublicationEvidence | None = None,
    cycles: tuple[R2CyclePITEvidence, ...] | None = None,
    audit_outcome: R2AuditExplanatoryOutcome | None = None,
) -> R2ExplanatoryTrialAssessment:
    """Evaluate one complete R2 synthetic graph through the public Domain entrypoint."""

    return evaluate_r2_explanatory_trial(
        policy=scenario.policy,
        taxonomy_publication=(
            scenario.taxonomy if taxonomy_publication is None else taxonomy_publication
        ),
        calendar_publication=scenario.calendar,
        cycle_evidence=scenario.cycles if cycles is None else cycles,
        audit_outcome=scenario.audit if audit_outcome is None else audit_outcome,
        assessed_at=NOW,
    )


def test_r2_contracts_and_trial_evaluation_reject_substituted_evidence() -> None:
    """R2 preserves proxy semantics and blocks publication, cycle, and audit substitutions."""

    scenario = build_r2_scenario()
    direct = scenario.policy.measure_semantics[0]
    proxy = scenario.policy.measure_semantics[1]

    with pytest.raises(ValueError, match="direct measure cannot carry proxy"):
        replace(direct, proxy_target_actor_code="foreign-investor")

    with pytest.raises(ValueError, match="bounded non-blank token"):
        replace(proxy, proxy_target_actor_code="")

    with pytest.raises(ValueError, match="bounded non-blank token"):
        R2EvidenceRef("", "v1", digest("empty-id"))

    with pytest.raises(ValueError, match="timezone-aware"):
        R2ExpectedPeriod(
            "period-with-naive-clock",
            datetime(2026, 8, 1),
            datetime(2026, 8, 2, tzinfo=UTC),
        )

    assessment = _evaluate_trial(scenario, taxonomy_publication=scenario.calendar)
    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.TAXONOMY_PUBLICATION_INVALID in assessment.blockers

    wrong_owner_cycle = replace(scenario.cycles[0], source_owner="foreign-owner")
    assessment = _evaluate_trial(scenario, cycles=(wrong_owner_cycle, scenario.cycles[1]))
    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID in assessment.blockers

    incomplete_cycle = replace(scenario.cycles[0], samples=scenario.cycles[0].samples[:-1])
    assessment = _evaluate_trial(scenario, cycles=(incomplete_cycle, scenario.cycles[1]))
    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.CYCLE_PERIOD_INCOMPLETE in assessment.blockers

    wrong_owner_audit = replace(scenario.audit, source_owner="foreign-owner")
    assessment = _evaluate_trial(scenario, audit_outcome=wrong_owner_audit)
    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.AUDIT_OUTCOME_INVALID in assessment.blockers


def test_r2_policy_and_monitoring_boundaries_preserve_fail_closed_status() -> None:
    """R2 policy ordering and an absent monitoring fact set remain explicit blockers."""

    scenario = build_r2_scenario()

    with pytest.raises(ValueError, match="canonical order"):
        replace(scenario.policy, expected_periods=tuple(reversed(scenario.policy.expected_periods)))

    with pytest.raises(ValueError, match="at-least direction"):
        replace(
            scenario.policy.metric_rules[0],
            direction=R2ThresholdDirection.AT_MOST,
        )

    with pytest.raises(ValueError, match="holm-v1"):
        replace(scenario.policy.multiple_testing, method_version="bonferroni")

    with pytest.raises(ValueError, match="finite Decimal"):
        R2MultipleTestingRule(
            family_id="r2-family",
            method_version="holm-v1",
            hypothesis_count=2,
            maximum_adjusted_p_value=Decimal("NaN"),
        )

    trial = _evaluate_trial(scenario)
    monitoring = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=trial,
        facts=(),
        assessed_at=NOW,
    )

    assert monitoring.status.value == "blocked"
    assert R2TrialBlockerCode.MONITORING_FACTS_MISSING in monitoring.blockers
