"""Boundary coverage for immutable R6 state-model evidence contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.advanced_state_model import (
    AdvancedStateMethodology,
    AdvancedStateModelAssessment,
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelBlockerCode,
    EconomicStateLabel,
    ExternalStateModelArtifact,
    StateModelLifecycleStatus,
    StateModelRetirementEvidence,
    StateProbability,
    StateProbabilityDistribution,
    StateTransitionRow,
    evaluate_advanced_state_model_evidence,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    acceptance_thresholds,
    artifact_attestation,
    complete_candidate,
    complete_pit_manifest,
    proven_shortfall_report,
)


def _evaluate(**changes: object) -> AdvancedStateModelAssessment:
    values: dict[str, object] = {
        "candidate": complete_candidate(),
        "baseline_shortfall": proven_shortfall_report(),
        "pit_manifest": complete_pit_manifest(),
        "artifact_attestation": artifact_attestation(),
        "thresholds": acceptance_thresholds(),
        "evaluated_at": NOW,
    }
    values.update(changes)
    return evaluate_advanced_state_model_evidence(**values)  # type: ignore[arg-type]


def test_input_and_pit_manifest_structural_validation() -> None:
    reference = complete_candidate().input_references[0]
    for mutation, match in (
        ({"input_key": ""}, "blank"),
        ({"input_key": "has space"}, "whitespace"),
        ({"content_hash": "bad"}, "sha256"),
        ({"pit_version_ids": ()}, "cannot be empty"),
        ({"pit_version_ids": (0,)}, "positive"),
        ({"pit_version_ids": (1, 1)}, "unique"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(reference, **mutation)

    manifest = complete_pit_manifest()
    for mutation, match in (
        ({"valid_until": manifest.as_of_time}, "must follow"),
        ({"is_verified": 1}, "booleans"),
        ({"coverage_ratio": Decimal("NaN")}, "finite"),
        ({"coverage_ratio": Decimal("1.1")}, "between zero and one"),
        ({"missing_count": -1}, "cannot be negative"),
        ({"inputs": ()}, "non-empty"),
        ({"inputs": (manifest.inputs[0], manifest.inputs[0])}, "uniquely keyed"),
        ({"as_of_time": datetime(2026, 1, 1)}, "timezone-aware"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(manifest, **mutation)


def test_economic_labels_probability_transition_and_duration_validation() -> None:
    candidate = complete_candidate()
    label = candidate.label_protocol.labels[0]
    with pytest.raises(ValueError, match="blank"):
        replace(label, economic_name="")
    protocol = candidate.label_protocol
    for mutation, match in (
        ({"is_stable": 1}, "booleans"),
        ({"labels": (label,)}, "at least two"),
        ({"labels": (label, label)}, "identities must be unique"),
        (
            {
                "labels": (
                    label,
                    EconomicStateLabel(
                        "another-state",
                        label.economic_name.upper(),
                        "Another economic definition.",
                    ),
                )
            },
            "names must be unique",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            replace(protocol, **mutation)

    with pytest.raises(ValueError, match="between zero and one"):
        StateProbability("expansion", Decimal("1.1"))
    probability = StateProbability("expansion", Decimal("0.5"))
    with pytest.raises(ValueError, match="uniquely keyed"):
        StateProbabilityDistribution(NOW, (probability, probability))
    with pytest.raises(ValueError, match="non-empty and unique"):
        StateTransitionRow("expansion", ())
    with pytest.raises(ValueError, match="uniquely keyed"):
        replace(
            candidate.transition_matrix,
            rows=(candidate.transition_matrix.rows[0],) * 2,
        )
    with pytest.raises(ValueError, match="positive"):
        replace(candidate.duration_evidence[0], mean_duration_periods=Decimal("0"))


def test_oos_baseline_policy_and_artifact_structural_validation() -> None:
    candidate = complete_candidate()
    metrics = candidate.oos_metrics
    for mutation, match in (
        ({"window_end": metrics.window_start}, "must follow"),
        ({"evaluated_at": metrics.window_end - timedelta(seconds=1)}, "cannot predate"),
        ({"sample_count": 0}, "positive"),
        ({"transition_accuracy": Decimal("1.1")}, "between zero and one"),
        ({"log_loss": Decimal("-1")}, "cannot be negative"),
        ({"evidence_hash": "bad"}, "sha256"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(metrics, **mutation)

    comparison = candidate.baseline_comparison
    with pytest.raises(ValueError, match="between zero and one"):
        replace(comparison, baseline_transition_accuracy=Decimal("1.1"))
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(comparison, baseline_log_loss=Decimal("-1"))

    policy = candidate.policy_reaction
    assert policy is not None
    with pytest.raises(ValueError, match="positive"):
        replace(policy, reaction_lag_periods=0)
    with pytest.raises(ValueError, match="non-empty"):
        replace(policy, targets=())
    with pytest.raises(ValueError, match="uniquely keyed"):
        replace(policy, targets=(policy.targets[0], policy.targets[0]))

    artifact = candidate.artifact
    with pytest.raises(ValueError, match="methodology"):
        replace(artifact, methodology="hidden_markov_model")
    with pytest.raises(ValueError, match="external_precomputed"):
        replace(artifact, computation_origin="internal_training")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(artifact, produced_at=datetime(2026, 1, 1))


def test_attestation_governance_threshold_and_retirement_validation() -> None:
    attestation = artifact_attestation()
    for mutation, match in (
        ({"methodology": "hidden_markov_model"}, "methodology"),
        ({"verified": 1}, "boolean"),
        ({"valid_until": attestation.observed_at}, "must follow"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(attestation, **mutation)

    candidate = complete_candidate()
    rule = candidate.governance_policy.invalidation_rules[0]
    with pytest.raises(ValueError, match="direction"):
        replace(rule, direction="below_minimum")
    governance = candidate.governance_policy
    with pytest.raises(ValueError, match="must follow"):
        replace(governance, valid_until=governance.activated_at)
    with pytest.raises(ValueError, match="non-empty"):
        replace(governance, invalidation_rules=())
    with pytest.raises(ValueError, match="non-empty and unique"):
        replace(governance, invalidation_rules=(rule, rule))

    thresholds = acceptance_thresholds()
    for mutation, match in (
        ({"minimum_transition_accuracy": Decimal("1.1")}, "between zero and one"),
        ({"maximum_log_loss": Decimal("-1")}, "cannot be negative"),
        ({"probability_sum_tolerance": Decimal("1")}, "must be in"),
        ({"minimum_duration_observations": 0}, "positive"),
        ({"valid_until": thresholds.activated_at}, "must follow"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(thresholds, **mutation)

    retirement = StateModelRetirementEvidence(
        event_id="retire-state-model-v1",
        retired_at=NOW,
        reason_codes=(rule.rule_id,),
        evidence_hash="7" * 64,
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(retirement, reason_codes=())
    with pytest.raises(ValueError, match="must be unique"):
        replace(retirement, reason_codes=(rule.rule_id, rule.rule_id))


def test_candidate_and_assessment_safety_invariants() -> None:
    candidate = complete_candidate()
    with pytest.raises(ValueError, match="methodology"):
        replace(candidate, methodology="hidden_markov_model")
    with pytest.raises(ValueError, match="non-empty and unique"):
        replace(candidate, input_references=())
    other_artifact = ExternalStateModelArtifact(
        **{
            **candidate.artifact.__dict__,
            "methodology": AdvancedStateMethodology.MARKOV_SWITCHING,
        }
    )
    with pytest.raises(ValueError, match="must match"):
        replace(candidate, artifact=other_artifact)
    with pytest.raises(ValueError, match="lifecycle"):
        replace(candidate, lifecycle_status="research_only")
    with pytest.raises(ValueError, match="requires retirement"):
        replace(candidate, lifecycle_status=StateModelLifecycleStatus.RETIRED)
    retirement = StateModelRetirementEvidence(
        "retire-state-model-v1",
        NOW,
        (candidate.governance_policy.invalidation_rules[0].rule_id,),
        "7" * 64,
    )
    with pytest.raises(ValueError, match="cannot carry"):
        replace(candidate, retirement_evidence=retirement)
    with pytest.raises(ValueError, match="must follow"):
        replace(candidate, valid_until=candidate.artifact.produced_at)
    with pytest.raises(ValueError, match="research-only"):
        replace(candidate, must_not_replace_regime=False)

    accepted = _evaluate()
    with pytest.raises(ValueError, match="status"):
        replace(accepted, status="accepted")
    with pytest.raises(ValueError, match="complete references"):
        replace(accepted, artifact_hash=None)
    with pytest.raises(ValueError, match="stable blockers"):
        AdvancedStateModelAssessment(
            status=AdvancedStateModelAssessmentStatus.BLOCKED,
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.candidate_version,
            methodology=candidate.methodology,
            artifact_hash=candidate.artifact.artifact_hash,
            pit_manifest_id=candidate.pit_manifest_id,
            pit_manifest_hash=candidate.pit_manifest_hash,
            label_protocol_version=candidate.label_protocol.protocol_version,
            assessed_at=NOW,
            blockers=(),
        )
    with pytest.raises(ValueError, match="cannot authorize"):
        replace(accepted, must_not_use_for_decision=False)


def test_remaining_evidence_gate_blockers_are_stable() -> None:
    candidate = complete_candidate()
    missing_sources = _evaluate(pit_manifest=None, artifact_attestation=None)
    pit_mismatch = _evaluate(pit_manifest=replace(complete_pit_manifest(), manifest_hash="8" * 64))
    unverified_artifact = _evaluate(
        artifact_attestation=replace(artifact_attestation(), verified=False)
    )
    future_artifact = _evaluate(
        artifact_attestation=replace(
            artifact_attestation(),
            observed_at=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(days=2),
        )
    )
    stale_artifact = _evaluate(
        artifact_attestation=replace(
            artifact_attestation(),
            valid_until=NOW - timedelta(seconds=1),
        )
    )
    future_evidence = _evaluate(
        candidate=replace(
            candidate,
            label_protocol=replace(
                candidate.label_protocol,
                verified_at=NOW + timedelta(hours=1),
            ),
        )
    )
    stale_candidate = _evaluate(
        candidate=replace(candidate, valid_until=NOW - timedelta(seconds=1))
    )
    short_duration = _evaluate(
        candidate=replace(
            candidate,
            duration_evidence=(
                replace(candidate.duration_evidence[0], observation_count=1),
                candidate.duration_evidence[1],
            ),
        )
    )
    wrong_threshold_version = _evaluate(
        thresholds=replace(acceptance_thresholds(), threshold_version="other-v1")
    )
    inactive_thresholds = _evaluate(
        thresholds=replace(
            acceptance_thresholds(),
            activated_at=NOW + timedelta(days=1),
            valid_until=NOW + timedelta(days=2),
        )
    )
    inactive_governance = _evaluate(
        candidate=replace(
            candidate,
            governance_policy=replace(
                candidate.governance_policy,
                activated_at=NOW + timedelta(days=1),
                valid_until=NOW + timedelta(days=2),
            ),
        )
    )

    assert {
        AdvancedStateModelBlockerCode.PIT_MANIFEST_MISSING,
        AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_MISSING,
    }.issubset(set(missing_sources.blockers))
    assert AdvancedStateModelBlockerCode.PIT_MANIFEST_MISMATCH in pit_mismatch.blockers
    assert (
        AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_UNVERIFIED
        in unverified_artifact.blockers
    )
    assert (
        AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_FROM_FUTURE in future_artifact.blockers
    )
    assert AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_STALE in stale_artifact.blockers
    assert AdvancedStateModelBlockerCode.EXTERNAL_EVIDENCE_FROM_FUTURE in future_evidence.blockers
    assert AdvancedStateModelBlockerCode.CANDIDATE_EVIDENCE_STALE in stale_candidate.blockers
    assert AdvancedStateModelBlockerCode.DURATION_EVIDENCE_INSUFFICIENT in short_duration.blockers
    assert (
        AdvancedStateModelBlockerCode.ACCEPTANCE_THRESHOLD_VERSION_MISMATCH
        in wrong_threshold_version.blockers
    )
    assert (
        AdvancedStateModelBlockerCode.ACCEPTANCE_THRESHOLDS_INACTIVE in inactive_thresholds.blockers
    )
    assert AdvancedStateModelBlockerCode.GOVERNANCE_POLICY_INACTIVE in inactive_governance.blockers
