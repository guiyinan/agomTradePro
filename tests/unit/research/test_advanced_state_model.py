"""Domain tests for fail-closed R6 advanced-state evidence acceptance."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from apps.research.domain.advanced_state_model import (
    AdvancedStateMethodology,
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelBlockerCode,
    StateProbability,
    StateTransitionRow,
    evaluate_advanced_state_model_evidence,
)
from apps.research.domain.state_model_baseline import (
    BaselineShortfallDecision,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    acceptance_thresholds,
    artifact_attestation,
    complete_candidate,
    complete_pit_manifest,
    proven_shortfall_report,
)

_DEFAULT = object()


def _evaluate(
    *,
    candidate=_DEFAULT,  # type: ignore[no-untyped-def]
    shortfall=_DEFAULT,  # type: ignore[no-untyped-def]
    manifest=_DEFAULT,  # type: ignore[no-untyped-def]
    attestation=_DEFAULT,  # type: ignore[no-untyped-def]
    thresholds=_DEFAULT,  # type: ignore[no-untyped-def]
):  # type: ignore[no-untyped-def]
    return evaluate_advanced_state_model_evidence(
        candidate=(complete_candidate() if candidate is _DEFAULT else candidate),
        baseline_shortfall=(proven_shortfall_report() if shortfall is _DEFAULT else shortfall),
        pit_manifest=(complete_pit_manifest() if manifest is _DEFAULT else manifest),
        artifact_attestation=(artifact_attestation() if attestation is _DEFAULT else attestation),
        thresholds=(acceptance_thresholds() if thresholds is _DEFAULT else thresholds),
        evaluated_at=NOW,
    )


def test_complete_external_hmm_evidence_is_accepted_only_for_research() -> None:
    assessment = _evaluate()

    assert assessment.status is AdvancedStateModelAssessmentStatus.ACCEPTED
    assert assessment.blockers == ()
    assert assessment.methodology is AdvancedStateMethodology.HIDDEN_MARKOV_MODEL
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


def test_baseline_shortfall_must_be_proven_and_bound_to_comparison() -> None:
    missing = _evaluate(shortfall=None)
    not_proven_report = replace(
        proven_shortfall_report(),
        decision=BaselineShortfallDecision.NOT_PROVEN,
        can_propose_advanced_model_research=False,
    )
    not_proven = _evaluate(shortfall=not_proven_report)
    mismatched = _evaluate(
        shortfall=replace(
            proven_shortfall_report(),
            evaluation_id="different-baseline-evaluation",
        )
    )

    assert AdvancedStateModelBlockerCode.BASELINE_SHORTFALL_MISSING in missing.blockers
    assert AdvancedStateModelBlockerCode.BASELINE_SHORTFALL_NOT_PROVEN in not_proven.blockers
    assert AdvancedStateModelBlockerCode.BASELINE_BINDING_MISMATCH in mismatched.blockers


def test_future_stale_and_incomplete_pit_evidence_fail_closed() -> None:
    future = _evaluate(
        manifest=replace(
            complete_pit_manifest(),
            as_of_time=NOW + timedelta(hours=1),
        )
    )
    stale = _evaluate(
        manifest=replace(
            complete_pit_manifest(),
            valid_until=NOW - timedelta(seconds=1),
        )
    )
    incomplete = _evaluate(
        manifest=replace(
            complete_pit_manifest(),
            is_complete=False,
            coverage_ratio=Decimal("0.90"),
            missing_count=1,
        )
    )

    assert AdvancedStateModelBlockerCode.PIT_MANIFEST_FROM_FUTURE in future.blockers
    assert AdvancedStateModelBlockerCode.PIT_MANIFEST_STALE in stale.blockers
    assert AdvancedStateModelBlockerCode.PIT_MANIFEST_INCOMPLETE in incomplete.blockers


def test_manifest_input_and_external_artifact_hash_tampering_are_blocked() -> None:
    candidate = complete_candidate()
    tampered_input = replace(candidate.input_references[0], content_hash="9" * 64)
    tampered_candidate = replace(
        candidate,
        input_references=(tampered_input, candidate.input_references[1]),
    )
    input_assessment = _evaluate(candidate=tampered_candidate)
    artifact_assessment = _evaluate(
        attestation=replace(artifact_attestation(), artifact_hash="8" * 64)
    )
    content_assessment = _evaluate(
        candidate=replace(
            candidate,
            hypothesis="Tampered after external evidence hash was sealed.",
        )
    )

    assert AdvancedStateModelBlockerCode.PIT_INPUT_VERSION_HASH_MISMATCH in (
        input_assessment.blockers
    )
    assert AdvancedStateModelBlockerCode.ARTIFACT_HASH_MISMATCH in (artifact_assessment.blockers)
    assert AdvancedStateModelBlockerCode.CANDIDATE_HASH_MISMATCH in (content_assessment.blockers)


def test_unstable_or_drifting_economic_labels_are_blocked() -> None:
    candidate = complete_candidate()
    unstable = _evaluate(
        candidate=replace(
            candidate,
            label_protocol=replace(candidate.label_protocol, is_stable=False),
        )
    )
    drift = _evaluate(
        candidate=replace(
            candidate,
            label_protocol=replace(candidate.label_protocol, drift_detected=True),
        )
    )
    missing_duration = _evaluate(
        candidate=replace(candidate, duration_evidence=candidate.duration_evidence[:1])
    )

    assert AdvancedStateModelBlockerCode.LABEL_PROTOCOL_UNSTABLE in unstable.blockers
    assert AdvancedStateModelBlockerCode.LABEL_DRIFT_DETECTED in drift.blockers
    assert AdvancedStateModelBlockerCode.LABEL_SET_MISMATCH in missing_duration.blockers


def test_probability_and_transition_rows_must_sum_to_one() -> None:
    candidate = complete_candidate()
    distribution = replace(
        candidate.state_distribution,
        probabilities=(
            StateProbability("expansion", Decimal("0.60")),
            StateProbability("slowdown", Decimal("0.30")),
        ),
    )
    first_row = StateTransitionRow(
        from_state_id="expansion",
        probabilities=(
            StateProbability("expansion", Decimal("0.60")),
            StateProbability("slowdown", Decimal("0.20")),
        ),
    )
    transition_matrix = replace(
        candidate.transition_matrix,
        rows=(first_row, candidate.transition_matrix.rows[1]),
    )

    distribution_assessment = _evaluate(
        candidate=replace(candidate, state_distribution=distribution)
    )
    transition_assessment = _evaluate(
        candidate=replace(candidate, transition_matrix=transition_matrix)
    )

    assert AdvancedStateModelBlockerCode.STATE_PROBABILITY_SUM_INVALID in (
        distribution_assessment.blockers
    )
    assert AdvancedStateModelBlockerCode.TRANSITION_ROW_SUM_INVALID in (
        transition_assessment.blockers
    )


def test_oos_metrics_must_clear_injected_thresholds_and_simple_baseline() -> None:
    candidate = complete_candidate()
    weak_metrics = replace(
        candidate.oos_metrics,
        transition_accuracy=Decimal("0.60"),
        log_loss=Decimal("0.70"),
        calibration_error=Decimal("0.20"),
    )
    assessment = _evaluate(candidate=replace(candidate, oos_metrics=weak_metrics))

    assert {
        AdvancedStateModelBlockerCode.OOS_TRANSITION_ACCURACY_BELOW_MINIMUM,
        AdvancedStateModelBlockerCode.OOS_LOG_LOSS_ABOVE_MAXIMUM,
        AdvancedStateModelBlockerCode.OOS_CALIBRATION_ABOVE_MAXIMUM,
        AdvancedStateModelBlockerCode.BASELINE_COMPARISON_NOT_IMPROVED,
    }.issubset(set(assessment.blockers))


def test_policy_target_contract_is_required_and_must_bind_pit_input_version() -> None:
    candidate = complete_candidate()
    missing = _evaluate(candidate=replace(candidate, policy_reaction=None))
    wrong_target = replace(
        candidate.policy_reaction.targets[0],  # type: ignore[union-attr]
        input_version="unbound-policy-input",
    )
    mismatched = _evaluate(
        candidate=replace(
            candidate,
            policy_reaction=replace(
                candidate.policy_reaction,  # type: ignore[arg-type]
                targets=(wrong_target,),
            ),
        )
    )

    assert AdvancedStateModelBlockerCode.POLICY_TARGET_CONTRACT_MISSING in missing.blockers
    assert AdvancedStateModelBlockerCode.POLICY_TARGET_INPUT_MISMATCH in mismatched.blockers
