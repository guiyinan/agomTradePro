"""R6 same-window comparison and policy-reaction qualification tests."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.advanced_state_model import (
    AdvancedStateModelAssessment,
    AdvancedStateModelAssessmentStatus,
    StateModelLifecycleStatus,
    StateModelRetirementEvidence,
)
from apps.research.domain.state_model_qualification import (
    AdvancedStateModelAssessmentAttestation,
    MetricImprovementDirection,
    PolicyCoefficientSign,
    StateModelQualificationAssessment,
    StateModelQualificationBlockerCode,
    StateModelQualificationStatus,
    attest_advanced_state_model_assessment,
    evaluate_state_model_qualification,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    acceptance_thresholds,
    artifact_attestation,
    complete_candidate,
    complete_pit_manifest,
    proven_shortfall_report,
)
from tests.unit.research.state_model_qualification_factories import (
    accepted_advanced_assessment,
    complete_derived_metric_bundle,
    complete_qualification_study,
    qualification_policy,
    study_preregistration,
)


def _reseal(study):  # type: ignore[no-untyped-def]
    return replace(study)


def _evaluate(**changes: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "candidate": complete_candidate(),
        "advanced_assessment": accepted_advanced_assessment(),
        "derived_metric_bundle": complete_derived_metric_bundle(),
        "baseline_shortfall": proven_shortfall_report(),
        "preregistration": study_preregistration(),
        "study": complete_qualification_study(),
        "policy": qualification_policy(),
        "assessed_at": NOW,
    }
    values.update(changes)
    return evaluate_state_model_qualification(**values)  # type: ignore[arg-type]


def test_complete_evidence_only_qualifies_for_manual_promotion_review() -> None:
    assessment = _evaluate()

    assert assessment.status is StateModelQualificationStatus.EVIDENCE_COMPLETE
    assert assessment.blockers == ()
    assert assessment.may_request_promotion_review is True
    assert assessment.promotion_decision_present is False
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


def test_qualification_assessment_has_no_public_zero_hash_constructor() -> None:
    assert hasattr(StateModelQualificationAssessment, "_from_gate") is False
    with pytest.raises(TypeError):
        StateModelQualificationAssessment()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        StateModelQualificationAssessment(content_hash="0" * 64)  # type: ignore[call-arg]


def test_complete_assessment_cannot_be_replayed_with_empty_metrics() -> None:
    assessment = _evaluate()
    fabricated = object.__new__(StateModelQualificationAssessment)
    for model_field in fields(assessment):
        value = (
            () if model_field.name == "metric_results" else getattr(assessment, model_field.name)
        )
        object.__setattr__(fabricated, model_field.name, value)

    with pytest.raises(ValueError, match="seven passed metrics"):
        fabricated.__post_init__()


def test_raw_s2_assessment_and_attestation_tamper_fail_closed() -> None:
    candidate = complete_candidate()
    raw_assessment = AdvancedStateModelAssessment(
        status=AdvancedStateModelAssessmentStatus.ACCEPTED,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        methodology=candidate.methodology,
        artifact_hash=candidate.artifact.artifact_hash,
        pit_manifest_id=candidate.pit_manifest_id,
        pit_manifest_hash=candidate.pit_manifest_hash,
        label_protocol_version=candidate.label_protocol.protocol_version,
        assessed_at=NOW - timedelta(minutes=30),
        blockers=(),
    )
    raw_result = _evaluate(advanced_assessment=raw_assessment)
    assert StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH in (
        raw_result.blockers
    )

    attestation = accepted_advanced_assessment()
    object.__setattr__(attestation, "threshold_hash", "f" * 64)
    tampered_result = _evaluate(advanced_assessment=attestation)
    assert StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_HASH_MISMATCH in (
        tampered_result.blockers
    )


def test_public_s2_attestation_factory_replays_exact_gate_and_rejects_fake_result() -> None:
    candidate = complete_candidate()
    raw_assessment = AdvancedStateModelAssessment(
        status=AdvancedStateModelAssessmentStatus.ACCEPTED,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        methodology=candidate.methodology,
        artifact_hash=candidate.artifact.artifact_hash,
        pit_manifest_id=candidate.pit_manifest_id,
        pit_manifest_hash=candidate.pit_manifest_hash,
        label_protocol_version=candidate.label_protocol.protocol_version,
        assessed_at=NOW - timedelta(minutes=30),
        blockers=(),
    )
    with pytest.raises(TypeError):
        attest_advanced_state_model_assessment(
            assessment_id="forged-s2",
            assessment=raw_assessment,  # type: ignore[call-arg]
            candidate=candidate,
            baseline_shortfall=proven_shortfall_report(),
            pit_manifest=complete_pit_manifest(),
            artifact_attestation=artifact_attestation(),
            thresholds=acceptance_thresholds(),
            evaluated_at=NOW - timedelta(minutes=30),
            evidence_ref="research://forged-s2",
        )
    with pytest.raises(TypeError):
        AdvancedStateModelAssessmentAttestation()  # type: ignore[call-arg]


@pytest.mark.parametrize("dependency", ("thresholds", "artifact", "pit"))
def test_s2_dependency_substitution_is_replayed_and_blocks_qualification(
    dependency: str,
) -> None:
    candidate = complete_candidate()
    thresholds = acceptance_thresholds()
    artifact = artifact_attestation()
    pit = complete_pit_manifest()
    if dependency == "thresholds":
        thresholds = replace(thresholds, minimum_transition_accuracy=Decimal("0.99"))
    elif dependency == "artifact":
        artifact = replace(artifact, verified=False)
    else:
        pit = replace(
            pit,
            is_complete=False,
            coverage_ratio=Decimal("0.9"),
            missing_count=1,
        )
    replayed = attest_advanced_state_model_assessment(
        assessment_id="advanced-state-assessment-v1",
        candidate=candidate,
        baseline_shortfall=proven_shortfall_report(),
        pit_manifest=pit,
        artifact_attestation=artifact,
        thresholds=thresholds,
        evaluated_at=NOW - timedelta(minutes=30),
        evidence_ref=f"research://r6/replayed/{dependency}",
    )

    assert replayed.status is AdvancedStateModelAssessmentStatus.BLOCKED
    assessment = _evaluate(advanced_assessment=replayed)
    assert StateModelQualificationBlockerCode.ADVANCED_GATE_NOT_ACCEPTED in assessment.blockers
    assert (
        StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH
        in assessment.blockers
    )


def test_resealed_study_cannot_substitute_s2_attestation_locator() -> None:
    study = complete_qualification_study()
    substituted = _reseal(replace(study, advanced_assessment_id="fabricated-s2-assessment"))

    assessment = _evaluate(study=substituted)

    assert StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH in (
        assessment.blockers
    )


def test_study_identity_is_content_addressed_and_same_id_payload_replacement_fails() -> None:
    original = complete_qualification_study()
    replacement = replace(original, evidence_ref="research://r6/different-body")

    assert original.study_id == original.calculated_study_id
    assert replacement.study_id == replacement.calculated_study_id
    assert replacement.study_id != original.study_id
    # ``dataclasses.replace`` reports an init=False override as ValueError on
    # Python 3.11 and TypeError on newer supported interpreters.
    with pytest.raises((TypeError, ValueError)):
        replace(
            original,
            study_id=original.study_id,
            evidence_ref="research://r6/caller-resealed-body",
        )

    object.__setattr__(replacement, "study_id", original.study_id)
    object.__setattr__(replacement, "content_hash", replacement.calculated_content_hash)
    assessment = _evaluate(study=replacement)

    assert StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH in assessment.blockers


def test_same_window_metrics_cover_duration_loss_complexity_and_label_stability() -> None:
    study = complete_qualification_study()
    weak_decision_loss = replace(study.metrics[4], candidate_value=Decimal("0.58"))
    weak_study = _reseal(
        replace(study, metrics=(*study.metrics[:4], weak_decision_loss, *study.metrics[5:]))
    )

    assessment = _evaluate(study=weak_study)

    assert StateModelQualificationBlockerCode.METRIC_MINIMUM_DELTA_NOT_MET in (assessment.blockers)
    results = {result.metric_key: result for result in assessment.metric_results}
    assert results["duration_mae_periods"].passed is True
    assert results["decision_loss_utility"].passed is False
    assert results["complexity_score"].passed is True
    assert results["label_stability_score"].passed is True


def test_resealed_study_cannot_fabricate_derived_metric_values() -> None:
    study = complete_qualification_study()
    fabricated = replace(study.metrics[4], candidate_value=Decimal("0.01"))
    resealed = _reseal(replace(study, metrics=(*study.metrics[:4], fabricated, *study.metrics[5:])))

    assessment = _evaluate(study=resealed)

    assert StateModelQualificationBlockerCode.DERIVED_METRIC_VALUE_MISMATCH in (assessment.blockers)


def test_derived_metric_bundle_seal_candidate_and_label_bindings_are_exact() -> None:
    bundle = complete_derived_metric_bundle()
    substituted_value = replace(bundle, decision_loss_utility=Decimal("0.01"))
    substituted_candidate = replace(bundle, candidate_evidence_hash="a" * 64)
    substituted_label = replace(bundle, label_stability_evidence_hash="b" * 64)

    value_result = _evaluate(derived_metric_bundle=substituted_value)
    candidate_result = _evaluate(derived_metric_bundle=substituted_candidate)
    label_result = _evaluate(derived_metric_bundle=substituted_label)

    assert StateModelQualificationBlockerCode.DERIVED_METRIC_VALUE_MISMATCH in (
        value_result.blockers
    )
    assert StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH in (
        candidate_result.blockers
    )
    assert StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH in (
        label_result.blockers
    )


def test_baseline_values_must_come_from_exact_sealed_shortfall_report() -> None:
    study = complete_qualification_study()
    substituted = replace(study.metrics[0], baseline_value=Decimal("0.30"))
    tampered = _reseal(replace(study, metrics=(substituted, *study.metrics[1:])))

    assessment = _evaluate(study=tampered)

    assert StateModelQualificationBlockerCode.BASELINE_METRIC_BINDING_MISMATCH in (
        assessment.blockers
    )


def test_candidate_oos_values_and_complete_identity_graph_are_recomputed() -> None:
    study = complete_qualification_study()
    substituted = replace(study.metrics[1], candidate_value=Decimal("0.20"))
    candidate_metric_tamper = _reseal(
        replace(study, metrics=(study.metrics[0], substituted, *study.metrics[2:]))
    )
    pit_tamper = _reseal(replace(study, pit_manifest_hash="9" * 64))
    label_tamper = _reseal(replace(study, label_stability_evidence_hash="8" * 64))

    metric_assessment = _evaluate(study=candidate_metric_tamper)
    pit_assessment = _evaluate(study=pit_tamper)
    label_assessment = _evaluate(study=label_tamper)

    assert StateModelQualificationBlockerCode.CANDIDATE_METRIC_BINDING_MISMATCH in (
        metric_assessment.blockers
    )
    assert StateModelQualificationBlockerCode.PIT_BINDING_MISMATCH in pit_assessment.blockers
    assert StateModelQualificationBlockerCode.LABEL_BINDING_MISMATCH in (label_assessment.blockers)


def test_preregistration_family_split_embargo_and_timing_are_exact() -> None:
    preregistration = study_preregistration()
    with pytest.raises(ValueError, match="before the OOS window"):
        replace(preregistration, registered_at=preregistration.oos_window_start)
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(preregistration, embargo_periods=-1)

    other_registration = replace(
        preregistration,
        split_policy_version="other-split-v1",
        content_hash="0" * 64,
    )
    other_registration = replace(
        other_registration,
        content_hash=other_registration.calculated_content_hash,
    )

    assessment = _evaluate(preregistration=other_registration)

    assert StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH in (
        assessment.blockers
    )


def test_study_tamper_future_stale_and_inactive_policy_fail_closed() -> None:
    study = complete_qualification_study()
    hash_tamper = replace(study)
    object.__setattr__(hash_tamper, "evidence_ref", "research://tampered")
    future_study = _reseal(
        replace(
            study,
            evaluated_at=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(days=2),
        )
    )
    stale_study = _reseal(replace(study, valid_until=NOW))
    policy = qualification_policy()
    inactive_policy = replace(
        policy,
        activated_at=NOW + timedelta(days=1),
        valid_until=NOW + timedelta(days=2),
    )

    assert (
        StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH
        in _evaluate(study=hash_tamper).blockers
    )
    assert (
        StateModelQualificationBlockerCode.STUDY_FROM_FUTURE
        in _evaluate(study=future_study).blockers
    )
    assert StateModelQualificationBlockerCode.STUDY_STALE in _evaluate(study=stale_study).blockers
    assert (
        StateModelQualificationBlockerCode.POLICY_INACTIVE
        in _evaluate(policy=inactive_policy).blockers
    )


def test_policy_coefficients_require_target_sign_significance_and_exact_contract() -> None:
    study = complete_qualification_study()
    coefficient = study.policy_coefficients[0]
    wrong_target = _reseal(
        replace(
            study,
            policy_coefficients=(replace(coefficient, target_code="unregistered-target"),),
        )
    )
    wrong_sign = _reseal(
        replace(
            study,
            policy_coefficients=(
                replace(
                    coefficient,
                    estimate=Decimal("-0.20"),
                    confidence_interval_lower=Decimal("-0.35"),
                    confidence_interval_upper=Decimal("-0.05"),
                ),
            ),
        )
    )
    insignificant = _reseal(
        replace(
            study,
            policy_coefficients=(replace(coefficient, p_value=Decimal("0.20")),),
        )
    )

    assert (
        StateModelQualificationBlockerCode.POLICY_TARGET_SET_MISMATCH
        in _evaluate(study=wrong_target).blockers
    )
    assert (
        StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGN_MISMATCH
        in _evaluate(study=wrong_sign).blockers
    )
    assert StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGNIFICANCE_FAILED in (
        _evaluate(study=insignificant).blockers
    )
    assert qualification_policy().coefficient_criteria[0].expected_sign is (
        PolicyCoefficientSign.POSITIVE
    )


def test_policy_diagnostics_and_advanced_gate_are_required() -> None:
    study = complete_qualification_study()
    diagnostics = replace(
        study.policy_diagnostics,
        adjusted_r_squared=Decimal("0.10"),
        residual_autocorrelation_p_value=Decimal("0.01"),
        heteroskedasticity_p_value=Decimal("0.01"),
        parameter_stability_p_value=Decimal("0.01"),
        condition_number=Decimal("100"),
    )
    weak_diagnostics = _reseal(replace(study, policy_diagnostics=diagnostics))
    advanced_assessment = attest_advanced_state_model_assessment(
        assessment_id="advanced-state-assessment-v1",
        candidate=complete_candidate(),
        baseline_shortfall=proven_shortfall_report(),
        pit_manifest=replace(complete_pit_manifest(), is_verified=False),
        artifact_attestation=artifact_attestation(),
        thresholds=acceptance_thresholds(),
        evaluated_at=NOW - timedelta(minutes=30),
        evidence_ref="research://r6/replayed/unverified-pit",
    )

    diagnostic_assessment = _evaluate(study=weak_diagnostics)
    gate_assessment = _evaluate(advanced_assessment=advanced_assessment)

    assert {
        StateModelQualificationBlockerCode.POLICY_ADJUSTED_R_SQUARED_FAILED,
        StateModelQualificationBlockerCode.POLICY_RESIDUAL_DIAGNOSTIC_FAILED,
        StateModelQualificationBlockerCode.POLICY_HETEROSKEDASTICITY_DIAGNOSTIC_FAILED,
        StateModelQualificationBlockerCode.POLICY_PARAMETER_STABILITY_FAILED,
        StateModelQualificationBlockerCode.POLICY_CONDITION_NUMBER_FAILED,
    }.issubset(set(diagnostic_assessment.blockers))
    assert StateModelQualificationBlockerCode.ADVANCED_GATE_NOT_ACCEPTED in (
        gate_assessment.blockers
    )


def test_structural_validation_rejects_naive_time_and_nonfinite_values() -> None:
    study = complete_qualification_study()
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(study, evaluated_at=datetime(2026, 8, 5, 12))
    with pytest.raises(ValueError, match="finite"):
        replace(study.metrics[0], candidate_value=Decimal("NaN"))


def test_fabricated_study_hash_is_rejected_by_the_qualification_gate() -> None:
    fabricated = complete_qualification_study()
    object.__setattr__(fabricated, "content_hash", "f" * 64)

    assessment = _evaluate(study=fabricated)

    assert StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH in assessment.blockers


def test_trial_family_split_embargo_and_policy_reaction_seals_are_rebound() -> None:
    study = complete_qualification_study()
    family_tamper = _reseal(replace(study, trial_family_id="different-family"))
    split_tamper = _reseal(replace(study, split_policy_version="different-split"))
    embargo_tamper = _reseal(replace(study, embargo_periods=3))
    reaction_tamper = _reseal(replace(study, policy_reaction_evidence_hash="7" * 64))

    for tampered in (family_tamper, split_tamper, embargo_tamper):
        assert StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH in (
            _evaluate(study=tampered).blockers
        )
    assert StateModelQualificationBlockerCode.POLICY_REACTION_BINDING_MISMATCH in (
        _evaluate(study=reaction_tamper).blockers
    )


def test_equal_oos_window_and_sample_count_are_not_caller_substitutable() -> None:
    study = complete_qualification_study()
    shifted_window = _reseal(
        replace(study, oos_window_start=study.oos_window_start + timedelta(days=1))
    )
    shifted_count = _reseal(replace(study, sample_count=study.sample_count - 1))

    assert (
        StateModelQualificationBlockerCode.OOS_WINDOW_MISMATCH
        in _evaluate(study=shifted_window).blockers
    )
    assert (
        StateModelQualificationBlockerCode.SAMPLE_COUNT_MISMATCH
        in _evaluate(study=shifted_count).blockers
    )


def test_label_drift_is_rechecked_from_the_authoritative_candidate() -> None:
    candidate = complete_candidate()
    unstable_labels = replace(
        candidate.label_protocol,
        is_stable=False,
        drift_detected=True,
    )
    draft = replace(
        candidate,
        label_protocol=unstable_labels,
        evidence_hash="0" * 64,
    )
    unstable_candidate = replace(draft, evidence_hash=draft.calculated_evidence_hash)

    assessment = _evaluate(candidate=unstable_candidate)

    assert StateModelQualificationBlockerCode.LABEL_PROTOCOL_UNSTABLE in assessment.blockers


def test_metric_direction_and_thresholds_come_only_from_the_sealed_policy() -> None:
    policy = qualification_policy()
    reversed_transition = replace(
        policy.metric_criteria[0],
        direction=MetricImprovementDirection.LOWER_IS_BETTER,
    )
    policy_draft = replace(
        policy,
        metric_criteria=(reversed_transition, *policy.metric_criteria[1:]),
        content_hash="0" * 64,
    )
    reversed_policy = replace(
        policy_draft,
        content_hash=policy_draft.calculated_content_hash,
    )

    assessment = _evaluate(policy=reversed_policy)

    results = {result.metric_key: result for result in assessment.metric_results}
    assert results["transition_accuracy"].direction is (MetricImprovementDirection.LOWER_IS_BETTER)
    assert results["transition_accuracy"].passed is False
    assert StateModelQualificationBlockerCode.METRIC_MINIMUM_DELTA_NOT_MET in (assessment.blockers)


def test_policy_must_cover_every_required_qualification_dimension() -> None:
    policy = qualification_policy()

    with pytest.raises(ValueError, match="exactly seven comparative metrics"):
        replace(
            policy,
            metric_criteria=policy.metric_criteria[:-1],
            content_hash="0" * 64,
        )


def test_retired_candidate_cannot_request_a_new_promotion_review() -> None:
    candidate = complete_candidate()
    retirement = StateModelRetirementEvidence(
        event_id="r6-retirement-event-v1",
        retired_at=NOW - timedelta(minutes=5),
        reason_codes=("label-instability",),
        evidence_hash="a" * 64,
    )
    draft = replace(
        candidate,
        lifecycle_status=StateModelLifecycleStatus.RETIRED,
        retirement_evidence=retirement,
        evidence_hash="0" * 64,
    )
    retired = replace(draft, evidence_hash=draft.calculated_evidence_hash)

    assessment = _evaluate(candidate=retired)

    assert StateModelQualificationBlockerCode.CANDIDATE_RETIRED in assessment.blockers
    assert assessment.may_request_promotion_review is False
