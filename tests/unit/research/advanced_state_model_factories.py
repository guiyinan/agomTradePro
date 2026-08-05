"""Complete external-evidence builders for R6 advanced-state tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.research.domain.advanced_state_model import (
    AdvancedStateMethodology,
    AdvancedStateModelAcceptanceThresholds,
    AdvancedStateModelCandidateEvidence,
    AdvancedStateModelGovernancePolicy,
    EconomicStateLabel,
    ExternalArtifactAttestation,
    ExternalStateModelArtifact,
    InvalidationDirection,
    PolicyReactionSpecification,
    PolicyTargetDefinition,
    SimpleBaselineComparisonEvidence,
    StateDurationEvidence,
    StateLabelProtocol,
    StateModelInputReference,
    StateModelInvalidationRule,
    StateModelLifecycleStatus,
    StateModelOOSMetrics,
    StateModelPITManifestEvidence,
    StateProbability,
    StateProbabilityDistribution,
    StateTransitionMatrixEvidence,
    StateTransitionRow,
)
from apps.research.domain.state_model_baseline import (
    BaselineEvidenceState,
    BaselineMetricObservation,
    BaselineShortfallDecision,
    BaselineShortfallReport,
    baseline_shortfall_report_hash,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def proven_shortfall_report() -> BaselineShortfallReport:
    """Return the exact PROVEN report bound by the candidate comparison."""

    metrics = (
        BaselineMetricObservation("transition_accuracy", "ratio", Decimal("0.55")),
        BaselineMetricObservation("log_loss", "score", Decimal("0.70")),
        BaselineMetricObservation("calibration_error", "score", Decimal("0.15")),
        BaselineMetricObservation("transition_false_negative_rate", "ratio", Decimal("0.25")),
        BaselineMetricObservation("decision_loss_utility", "score", Decimal("0.60")),
    )
    metric_results = (
        ("transition_false_negative_rate", True),
        ("decision_loss_utility", True),
    )
    window_start = NOW - timedelta(days=365)
    window_end = NOW - timedelta(days=7)
    evidence_evaluated_at = NOW - timedelta(hours=4)
    evidence_valid_until = NOW + timedelta(days=7)
    evidence_refs = ("research://baseline-evaluation-v1",)
    content_hash = baseline_shortfall_report_hash(
        specification_version="regime-simple-shortfall.v1",
        evaluation_id="baseline-evaluation-v1",
        baseline_key="regime.simple.pmi-cpi",
        baseline_version="regime-v2",
        pit_manifest_id="pit-r6-state-model-v1",
        window_start=window_start,
        window_end=window_end,
        observation_count=240,
        metrics=metrics,
        evidence_refs=evidence_refs,
        evidence_evaluated_at=evidence_evaluated_at,
        evidence_valid_until=evidence_valid_until,
        evidence_state=BaselineEvidenceState.VERIFIED,
        decision=BaselineShortfallDecision.PROVEN,
        can_propose_advanced_model_research=True,
        metric_results=metric_results,
        blockers=(),
    )
    return BaselineShortfallReport(
        specification_version="regime-simple-shortfall.v1",
        evaluation_id="baseline-evaluation-v1",
        baseline_key="regime.simple.pmi-cpi",
        baseline_version="regime-v2",
        pit_manifest_id="pit-r6-state-model-v1",
        window_start=window_start,
        window_end=window_end,
        observation_count=240,
        metrics=metrics,
        evidence_refs=evidence_refs,
        evidence_evaluated_at=evidence_evaluated_at,
        evidence_valid_until=evidence_valid_until,
        evidence_state=BaselineEvidenceState.VERIFIED,
        decision=BaselineShortfallDecision.PROVEN,
        can_propose_advanced_model_research=True,
        metric_results=metric_results,
        blockers=(),
        content_hash=content_hash,
    )


def input_references() -> tuple[StateModelInputReference, ...]:
    """Return exact version/hash references sealed by the PIT manifest."""

    return (
        StateModelInputReference(
            input_key="growth_features",
            dataset_key="macro.growth.vintage",
            input_version="growth-input-v3",
            content_hash="a" * 64,
            pit_version_ids=(101, 102),
        ),
        StateModelInputReference(
            input_key="policy_target",
            dataset_key="macro.policy.target",
            input_version="policy-target-v2",
            content_hash="b" * 64,
            pit_version_ids=(201, 202),
        ),
    )


def complete_pit_manifest() -> StateModelPITManifestEvidence:
    """Return a complete, current canonical PIT manifest."""

    return StateModelPITManifestEvidence(
        manifest_id="pit-r6-state-model-v1",
        manifest_hash="c" * 64,
        as_of_time=NOW - timedelta(days=2),
        valid_until=NOW + timedelta(days=2),
        is_verified=True,
        is_complete=True,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        inputs=input_references(),
    )


def artifact_attestation() -> ExternalArtifactAttestation:
    """Return owner-attested external artifact evidence."""

    return ExternalArtifactAttestation(
        artifact_id="external-hmm-artifact-v1",
        methodology=AdvancedStateMethodology.HIDDEN_MARKOV_MODEL,
        artifact_hash="d" * 64,
        verified=True,
        observed_at=NOW - timedelta(days=1, hours=2),
        valid_until=NOW + timedelta(days=7),
        evidence_ref="research-runner://trial-r6-42/artifact",
    )


def acceptance_thresholds() -> AdvancedStateModelAcceptanceThresholds:
    """Return versioned, injected acceptance thresholds."""

    return AdvancedStateModelAcceptanceThresholds(
        threshold_version="advanced-state-acceptance-v1",
        minimum_transition_accuracy=Decimal("0.65"),
        maximum_log_loss=Decimal("0.55"),
        maximum_calibration_error=Decimal("0.10"),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_duration_observations=20,
        activated_at=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
    )


def complete_candidate() -> AdvancedStateModelCandidateEvidence:
    """Return complete externally precomputed HMM research evidence."""

    labels = (
        EconomicStateLabel(
            state_id="expansion",
            economic_name="Broad-based expansion",
            economic_definition="Growth improves while inflation remains contained.",
        ),
        EconomicStateLabel(
            state_id="slowdown",
            economic_name="Demand slowdown",
            economic_definition="Growth momentum weakens with tighter financial conditions.",
        ),
    )
    candidate = AdvancedStateModelCandidateEvidence(
        candidate_id="advanced-state-candidate-v1",
        candidate_version="advanced-state-hmm-v1",
        methodology=AdvancedStateMethodology.HIDDEN_MARKOV_MODEL,
        hypothesis="Stable hidden states improve transition detection over the simple baseline.",
        baseline_comparison=SimpleBaselineComparisonEvidence(
            baseline_key="regime.simple.pmi-cpi",
            baseline_version="regime-v2",
            shortfall_specification_version="regime-simple-shortfall.v1",
            shortfall_evaluation_id="baseline-evaluation-v1",
            shortfall_report_hash=proven_shortfall_report().content_hash,
            compared_at=NOW - timedelta(hours=3),
            evidence_ref="research://baseline-comparison-v1",
            evidence_hash="1" * 64,
        ),
        pit_manifest_id="pit-r6-state-model-v1",
        pit_manifest_hash="c" * 64,
        input_references=input_references(),
        label_protocol=StateLabelProtocol(
            protocol_version="economic-state-labels-v1",
            alignment_method="anchor-signature-and-centroid-v1",
            labels=labels,
            stability_evidence_ref="research://label-stability-v1",
            stability_evidence_hash="2" * 64,
            verified_at=NOW - timedelta(hours=4),
            is_stable=True,
            drift_detected=False,
        ),
        state_distribution=StateProbabilityDistribution(
            observed_at=NOW - timedelta(hours=5),
            probabilities=(
                StateProbability("expansion", Decimal("0.70")),
                StateProbability("slowdown", Decimal("0.30")),
            ),
        ),
        transition_matrix=StateTransitionMatrixEvidence(
            matrix_version="transition-matrix-v1",
            observed_at=NOW - timedelta(hours=5),
            horizon_periods=1,
            rows=(
                StateTransitionRow(
                    from_state_id="expansion",
                    probabilities=(
                        StateProbability("expansion", Decimal("0.80")),
                        StateProbability("slowdown", Decimal("0.20")),
                    ),
                ),
                StateTransitionRow(
                    from_state_id="slowdown",
                    probabilities=(
                        StateProbability("expansion", Decimal("0.25")),
                        StateProbability("slowdown", Decimal("0.75")),
                    ),
                ),
            ),
        ),
        duration_evidence=(
            StateDurationEvidence("expansion", Decimal("8.5"), Decimal("7"), 42),
            StateDurationEvidence("slowdown", Decimal("5.2"), Decimal("4"), 35),
        ),
        oos_metrics=StateModelOOSMetrics(
            window_start=NOW - timedelta(days=365),
            window_end=NOW - timedelta(days=7),
            sample_count=240,
            transition_accuracy=Decimal("0.72"),
            log_loss=Decimal("0.48"),
            calibration_error=Decimal("0.08"),
            duration_mae_periods=Decimal("1.4"),
            evaluated_at=NOW - timedelta(hours=3),
            evidence_ref="research://oos-state-metrics-v1",
            evidence_hash="3" * 64,
        ),
        policy_reaction=PolicyReactionSpecification(
            specification_version="policy-reaction-v1",
            policy_instrument_code="policy_rate",
            reaction_equation_version="reaction-equation-v2",
            reaction_lag_periods=1,
            targets=(
                PolicyTargetDefinition(
                    target_code="policy_growth_target",
                    dataset_key="macro.policy.target",
                    input_version="policy-target-v2",
                    unit="index",
                    economic_role="growth_stabilization",
                ),
            ),
            evidence_ref="research://policy-reaction-contract-v1",
            evidence_hash="4" * 64,
        ),
        artifact=ExternalStateModelArtifact(
            artifact_id="external-hmm-artifact-v1",
            methodology=AdvancedStateMethodology.HIDDEN_MARKOV_MODEL,
            producer_ref="research-runner:trial-r6-42",
            produced_at=NOW - timedelta(hours=2),
            code_version="git:abcdef0123456789",
            parameter_version="hmm-params-v4",
            parameter_hash="5" * 64,
            artifact_hash="d" * 64,
            computation_origin="external_precomputed",
        ),
        acceptance_threshold_version="advanced-state-acceptance-v1",
        governance_policy=AdvancedStateModelGovernancePolicy(
            policy_version="advanced-state-governance-v1",
            activated_at=NOW - timedelta(days=30),
            valid_until=NOW + timedelta(days=30),
            invalidation_rules=(
                StateModelInvalidationRule(
                    rule_id="transition-accuracy-floor",
                    metric_name="oos.transition_accuracy",
                    direction=InvalidationDirection.BELOW_MINIMUM,
                    threshold=Decimal("0.60"),
                    consecutive_windows=2,
                ),
            ),
            retirement_owner="research-owner",
            retirement_protocol_version="state-model-retirement-v1",
        ),
        lifecycle_status=StateModelLifecycleStatus.RESEARCH_ONLY,
        retirement_evidence=None,
        valid_until=NOW + timedelta(days=7),
        evidence_hash="0" * 64,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )
    return replace(candidate, evidence_hash=candidate.calculated_evidence_hash)
