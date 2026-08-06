"""Builders for the R6 comparative qualification evidence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from apps.research.domain.state_model_qualification import (
    AdvancedStateModelAssessmentAttestation,
    ComparativeMetricCriterion,
    ComparativeMetricEvidence,
    MetricImprovementDirection,
    PolicyCoefficientCriterion,
    PolicyCoefficientSign,
    PolicyReactionCoefficientEvidence,
    PolicyReactionDiagnosticEvidence,
    StateModelComparativeStudyEvidence,
    StateModelDerivedMetricBundle,
    StateModelQualificationPolicy,
    StateModelStudyPreregistration,
    attest_advanced_state_model_assessment,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    acceptance_thresholds,
    artifact_attestation,
    complete_candidate,
    complete_pit_manifest,
    proven_shortfall_report,
)


def accepted_advanced_assessment() -> AdvancedStateModelAssessmentAttestation:
    """Return the exact research-only S2 assessment used by qualification."""

    candidate = complete_candidate()
    return attest_advanced_state_model_assessment(
        assessment_id="advanced-state-assessment-v1",
        candidate=candidate,
        baseline_shortfall=proven_shortfall_report(),
        pit_manifest=complete_pit_manifest(),
        artifact_attestation=artifact_attestation(),
        thresholds=acceptance_thresholds(),
        evaluated_at=NOW - timedelta(minutes=30),
        evidence_ref="research://r6/advanced-assessment/v1",
    )


def complete_derived_metric_bundle() -> StateModelDerivedMetricBundle:
    """Return the exact sealed owner bundle for three derived metrics."""

    candidate = complete_candidate()
    return StateModelDerivedMetricBundle(
        bundle_id="r6-derived-metrics-v1",
        bundle_version="v1",
        provider="research-derived-metric-provider-v1",
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_evidence_hash=candidate.evidence_hash,
        label_protocol_version=candidate.label_protocol.protocol_version,
        label_stability_evidence_hash=candidate.label_protocol.stability_evidence_hash,
        decision_loss_utility=Decimal("0.42"),
        complexity_score=Decimal("0.30"),
        label_stability_score=Decimal("0.90"),
        evaluated_at=NOW - timedelta(minutes=25),
        valid_until=NOW + timedelta(days=5),
        evidence_ref="research://r6/derived-metrics/v1",
    )


def qualification_policy() -> StateModelQualificationPolicy:
    """Return fully injected comparison and policy-diagnostic thresholds."""

    criteria = (
        ComparativeMetricCriterion(
            "transition_accuracy",
            "ratio",
            MetricImprovementDirection.HIGHER_IS_BETTER,
            Decimal("0.10"),
        ),
        ComparativeMetricCriterion(
            "log_loss",
            "score",
            MetricImprovementDirection.LOWER_IS_BETTER,
            Decimal("0.10"),
        ),
        ComparativeMetricCriterion(
            "calibration_error",
            "score",
            MetricImprovementDirection.LOWER_IS_BETTER,
            Decimal("0.05"),
        ),
        ComparativeMetricCriterion(
            "duration_mae_periods",
            "periods",
            MetricImprovementDirection.LOWER_IS_BETTER,
            Decimal("0.50"),
        ),
        ComparativeMetricCriterion(
            "decision_loss_utility",
            "score",
            MetricImprovementDirection.LOWER_IS_BETTER,
            Decimal("0.10"),
        ),
        ComparativeMetricCriterion(
            "complexity_score",
            "score",
            MetricImprovementDirection.LOWER_IS_BETTER,
            Decimal("-0.25"),
        ),
        ComparativeMetricCriterion(
            "label_stability_score",
            "score",
            MetricImprovementDirection.HIGHER_IS_BETTER,
            Decimal("0.10"),
        ),
    )
    draft = StateModelQualificationPolicy(
        policy_version="state-model-qualification-v1",
        activated_at=NOW - timedelta(days=500),
        valid_until=NOW + timedelta(days=30),
        metric_criteria=criteria,
        coefficient_criteria=(
            PolicyCoefficientCriterion(
                coefficient_key="growth_target_lag_1",
                target_code="policy_growth_target",
                lag_periods=1,
                expected_sign=PolicyCoefficientSign.POSITIVE,
                maximum_p_value=Decimal("0.05"),
                minimum_absolute_estimate=Decimal("0.10"),
            ),
        ),
        minimum_policy_sample_count=100,
        minimum_adjusted_r_squared=Decimal("0.30"),
        minimum_residual_autocorrelation_p_value=Decimal("0.05"),
        minimum_heteroskedasticity_p_value=Decimal("0.05"),
        minimum_parameter_stability_p_value=Decimal("0.05"),
        maximum_condition_number=Decimal("50"),
        content_hash="0" * 64,
    )
    return replace(draft, content_hash=draft.calculated_content_hash)


def study_preregistration() -> StateModelStudyPreregistration:
    """Return a preregistration fixed before the OOS window begins."""

    candidate = complete_candidate()
    report = proven_shortfall_report()
    policy = qualification_policy()
    draft = StateModelStudyPreregistration(
        registration_id="r6-comparative-study-registration-v1",
        trial_family_id="r6-state-family-v1",
        trial_family_hash="6" * 64,
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        methodology=candidate.methodology,
        baseline_shortfall_report_hash=report.content_hash,
        qualification_policy_version=policy.policy_version,
        qualification_policy_hash=policy.content_hash,
        oos_window_start=candidate.oos_metrics.window_start,
        oos_window_end=candidate.oos_metrics.window_end,
        split_policy_version="purged-walk-forward-v1",
        embargo_periods=2,
        registered_at=candidate.oos_metrics.window_start - timedelta(days=30),
        evidence_ref="research://r6/preregistration/v1",
        content_hash="0" * 64,
    )
    return replace(draft, content_hash=draft.calculated_content_hash)


def complete_qualification_study() -> StateModelComparativeStudyEvidence:
    """Return same-window candidate/baseline and policy-reaction evidence."""

    candidate = complete_candidate()
    report = proven_shortfall_report()
    preregistration = study_preregistration()
    policy = qualification_policy()
    advanced_assessment = accepted_advanced_assessment()
    derived_metrics = complete_derived_metric_bundle()
    metrics = (
        ComparativeMetricEvidence("transition_accuracy", "ratio", Decimal("0.55"), Decimal("0.72")),
        ComparativeMetricEvidence("log_loss", "score", Decimal("0.70"), Decimal("0.48")),
        ComparativeMetricEvidence("calibration_error", "score", Decimal("0.15"), Decimal("0.08")),
        ComparativeMetricEvidence(
            "duration_mae_periods", "periods", Decimal("2.10"), Decimal("1.40")
        ),
        ComparativeMetricEvidence(
            "decision_loss_utility", "score", Decimal("0.60"), Decimal("0.42")
        ),
        ComparativeMetricEvidence("complexity_score", "score", Decimal("0.10"), Decimal("0.30")),
        ComparativeMetricEvidence(
            "label_stability_score", "score", Decimal("0.70"), Decimal("0.90")
        ),
    )
    return StateModelComparativeStudyEvidence(
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_evidence_hash=candidate.evidence_hash,
        artifact_hash=candidate.artifact.artifact_hash,
        advanced_assessment_id=advanced_assessment.assessment_id,
        advanced_assessment_hash=advanced_assessment.content_hash,
        advanced_pit_manifest_canonical_hash=(advanced_assessment.pit_manifest_canonical_hash),
        advanced_artifact_attestation_hash=(advanced_assessment.artifact_attestation_hash),
        advanced_threshold_hash=advanced_assessment.threshold_hash,
        derived_metric_bundle_id=derived_metrics.bundle_id,
        derived_metric_bundle_version=derived_metrics.bundle_version,
        derived_metric_bundle_hash=derived_metrics.content_hash,
        baseline_shortfall_specification_version=report.specification_version,
        baseline_shortfall_evaluation_id=report.evaluation_id,
        baseline_shortfall_report_hash=report.content_hash,
        pit_manifest_id=candidate.pit_manifest_id,
        pit_manifest_hash=candidate.pit_manifest_hash,
        label_protocol_version=candidate.label_protocol.protocol_version,
        label_stability_evidence_hash=candidate.label_protocol.stability_evidence_hash,
        preregistration_id=preregistration.registration_id,
        preregistration_hash=preregistration.content_hash,
        trial_family_id=preregistration.trial_family_id,
        trial_family_hash=preregistration.trial_family_hash,
        split_policy_version=preregistration.split_policy_version,
        embargo_periods=preregistration.embargo_periods,
        qualification_policy_version=policy.policy_version,
        qualification_policy_hash=policy.content_hash,
        policy_reaction_specification_version=(
            candidate.policy_reaction.specification_version
            if candidate.policy_reaction is not None
            else "missing"
        ),
        policy_reaction_evidence_hash=(
            candidate.policy_reaction.evidence_hash
            if candidate.policy_reaction is not None
            else "0" * 64
        ),
        oos_window_start=candidate.oos_metrics.window_start,
        oos_window_end=candidate.oos_metrics.window_end,
        sample_count=candidate.oos_metrics.sample_count,
        metrics=metrics,
        policy_coefficients=(
            PolicyReactionCoefficientEvidence(
                coefficient_key="growth_target_lag_1",
                target_code="policy_growth_target",
                lag_periods=1,
                estimate=Decimal("0.45"),
                standard_error=Decimal("0.10"),
                confidence_interval_lower=Decimal("0.25"),
                confidence_interval_upper=Decimal("0.65"),
                p_value=Decimal("0.01"),
            ),
        ),
        policy_diagnostics=PolicyReactionDiagnosticEvidence(
            sample_count=candidate.oos_metrics.sample_count,
            adjusted_r_squared=Decimal("0.52"),
            residual_autocorrelation_p_value=Decimal("0.25"),
            heteroskedasticity_p_value=Decimal("0.20"),
            parameter_stability_p_value=Decimal("0.15"),
            condition_number=Decimal("12"),
        ),
        evaluated_at=NOW - timedelta(minutes=20),
        valid_until=NOW + timedelta(days=5),
        evidence_ref="research://r6/comparative-study/v1",
    )
