"""Fail-closed R6 comparative qualification evidence contracts.

This module compares an externally produced advanced-state candidate with the
sealed simple baseline on one pre-registered out-of-sample window.  A complete
assessment is only evidence for a later human promotion review.  It never
publishes a current state, authorizes a decision, or replaces canonical Regime.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from apps.research.domain.advanced_state_model import (
    AdvancedStateMethodology,
    AdvancedStateModelAcceptanceThresholds,
    AdvancedStateModelAssessment,
    AdvancedStateModelAssessmentStatus,
    AdvancedStateModelBlockerCode,
    AdvancedStateModelCandidateEvidence,
    ExternalArtifactAttestation,
    StateModelLifecycleStatus,
    StateModelPITManifestEvidence,
    evaluate_advanced_state_model_evidence,
)
from apps.research.domain.state_model_baseline import (
    BaselineEvidenceState,
    BaselineShortfallDecision,
    BaselineShortfallReport,
)

REQUIRED_QUALIFICATION_METRIC_KEYS = frozenset(
    {
        "transition_accuracy",
        "log_loss",
        "calibration_error",
        "duration_mae_periods",
        "decision_loss_utility",
        "complexity_score",
        "label_stability_score",
    }
)


def _require_text(value: str, field_name: str, *, maximum: int = 500) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank string")


def _require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    return value


def _canonical_hash(value: object, *, excluded_fields: frozenset[str] = frozenset()) -> str:
    if not is_dataclass(value):
        raise TypeError("canonical hash input must be a dataclass")
    payload = {
        field.name: _canonical_value(getattr(value, field.name))
        for field in fields(value)
        if field.name not in excluded_fields
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MetricImprovementDirection(str, Enum):
    """Governed direction in which a candidate metric improves."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class PolicyCoefficientSign(str, Enum):
    """Pre-registered expected sign for one policy-reaction coefficient."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class StateModelQualificationStatus(str, Enum):
    """Outcome of the R6 comparative qualification gate."""

    EVIDENCE_COMPLETE = "evidence_complete"
    BLOCKED = "blocked"


class StateModelQualificationBlockerCode(str, Enum):
    """Stable reasons why an R6 qualification study cannot advance."""

    STUDY_MISSING = "state_model_qualification.study.missing"
    STUDY_BINDING_MISMATCH = "state_model_qualification.study.binding_mismatch"
    STUDY_HASH_MISMATCH = "state_model_qualification.study.hash_mismatch"
    STUDY_FROM_FUTURE = "state_model_qualification.study.from_future"
    STUDY_STALE = "state_model_qualification.study.stale"
    PREREGISTRATION_MISSING = "state_model_qualification.preregistration.missing"
    PREREGISTRATION_HASH_MISMATCH = "state_model_qualification.preregistration.hash_mismatch"
    PREREGISTRATION_BINDING_MISMATCH = "state_model_qualification.preregistration.binding_mismatch"
    CANDIDATE_MISSING = "state_model_qualification.candidate.missing"
    CANDIDATE_HASH_MISMATCH = "state_model_qualification.candidate.hash_mismatch"
    CANDIDATE_BINDING_MISMATCH = "state_model_qualification.candidate.binding_mismatch"
    CANDIDATE_EVIDENCE_STALE = "state_model_qualification.candidate.stale"
    CANDIDATE_RETIRED = "state_model_qualification.candidate.retired"
    CANDIDATE_METRIC_BINDING_MISMATCH = (
        "state_model_qualification.candidate.metric_binding_mismatch"
    )
    ADVANCED_ASSESSMENT_MISSING = "state_model_qualification.advanced_gate.missing"
    ADVANCED_ASSESSMENT_HASH_MISMATCH = "state_model_qualification.advanced_gate.hash_mismatch"
    ADVANCED_GATE_NOT_ACCEPTED = "state_model_qualification.advanced_gate.not_accepted"
    ADVANCED_ASSESSMENT_BINDING_MISMATCH = (
        "state_model_qualification.advanced_gate.binding_mismatch"
    )
    DERIVED_METRIC_BUNDLE_MISSING = "state_model_qualification.derived_metrics.missing"
    DERIVED_METRIC_BUNDLE_HASH_MISMATCH = "state_model_qualification.derived_metrics.hash_mismatch"
    DERIVED_METRIC_BUNDLE_BINDING_MISMATCH = (
        "state_model_qualification.derived_metrics.binding_mismatch"
    )
    DERIVED_METRIC_VALUE_MISMATCH = "state_model_qualification.derived_metrics.value_mismatch"
    DERIVED_METRIC_BUNDLE_FROM_FUTURE = "state_model_qualification.derived_metrics.from_future"
    DERIVED_METRIC_BUNDLE_STALE = "state_model_qualification.derived_metrics.stale"
    BASELINE_SHORTFALL_MISSING = "state_model_qualification.baseline.missing"
    BASELINE_SHORTFALL_NOT_PROVEN = "state_model_qualification.baseline.not_proven"
    BASELINE_REPORT_HASH_MISMATCH = "state_model_qualification.baseline.hash_mismatch"
    BASELINE_METRIC_BINDING_MISMATCH = "state_model_qualification.baseline.metric_binding_mismatch"
    BASELINE_EVIDENCE_FROM_FUTURE = "state_model_qualification.baseline.from_future"
    BASELINE_EVIDENCE_STALE = "state_model_qualification.baseline.stale"
    PIT_BINDING_MISMATCH = "state_model_qualification.pit.binding_mismatch"
    LABEL_BINDING_MISMATCH = "state_model_qualification.label.binding_mismatch"
    LABEL_PROTOCOL_UNSTABLE = "state_model_qualification.label.unstable"
    POLICY_MISSING = "state_model_qualification.policy.missing"
    POLICY_HASH_MISMATCH = "state_model_qualification.policy.hash_mismatch"
    POLICY_BINDING_MISMATCH = "state_model_qualification.policy.binding_mismatch"
    POLICY_INACTIVE = "state_model_qualification.policy.inactive"
    OOS_WINDOW_MISMATCH = "state_model_qualification.window.mismatch"
    SAMPLE_COUNT_MISMATCH = "state_model_qualification.sample_count.mismatch"
    METRIC_SET_MISMATCH = "state_model_qualification.metric.set_mismatch"
    METRIC_UNIT_MISMATCH = "state_model_qualification.metric.unit_mismatch"
    METRIC_MINIMUM_DELTA_NOT_MET = "state_model_qualification.metric.delta_not_met"
    POLICY_TARGET_SET_MISMATCH = "state_model_qualification.policy.target_set_mismatch"
    POLICY_REACTION_BINDING_MISMATCH = "state_model_qualification.policy.reaction_binding_mismatch"
    POLICY_COEFFICIENT_SIGN_MISMATCH = "state_model_qualification.policy.coefficient_sign_mismatch"
    POLICY_COEFFICIENT_SIGNIFICANCE_FAILED = (
        "state_model_qualification.policy.coefficient_significance_failed"
    )
    POLICY_COEFFICIENT_MAGNITUDE_FAILED = (
        "state_model_qualification.policy.coefficient_magnitude_failed"
    )
    POLICY_COEFFICIENT_INTERVAL_FAILED = (
        "state_model_qualification.policy.coefficient_interval_failed"
    )
    POLICY_SAMPLE_INSUFFICIENT = "state_model_qualification.policy.sample_insufficient"
    POLICY_ADJUSTED_R_SQUARED_FAILED = "state_model_qualification.policy.adjusted_r_squared_failed"
    POLICY_RESIDUAL_DIAGNOSTIC_FAILED = (
        "state_model_qualification.policy.residual_diagnostic_failed"
    )
    POLICY_HETEROSKEDASTICITY_DIAGNOSTIC_FAILED = (
        "state_model_qualification.policy.heteroskedasticity_diagnostic_failed"
    )
    POLICY_PARAMETER_STABILITY_FAILED = (
        "state_model_qualification.policy.parameter_stability_failed"
    )
    POLICY_CONDITION_NUMBER_FAILED = "state_model_qualification.policy.condition_number_failed"
    EVIDENCE_TIMELINE_INVALID = "state_model_qualification.evidence.timeline_invalid"


@dataclass(frozen=True)
class ComparativeMetricCriterion:
    """One versioned, externally injected candidate improvement threshold."""

    metric_key: str
    unit: str
    direction: MetricImprovementDirection
    minimum_improvement_delta: Decimal

    def __post_init__(self) -> None:
        _require_token(self.metric_key, "ComparativeMetricCriterion.metric_key")
        _require_token(self.unit, "ComparativeMetricCriterion.unit")
        if not isinstance(self.direction, MetricImprovementDirection):
            raise ValueError("comparative metric direction is invalid")
        _require_finite(
            self.minimum_improvement_delta,
            "ComparativeMetricCriterion.minimum_improvement_delta",
        )

    def improvement_delta(self, *, baseline: Decimal, candidate: Decimal) -> Decimal:
        """Return direction-normalized improvement without a hidden default."""

        _require_finite(baseline, "baseline metric value")
        _require_finite(candidate, "candidate metric value")
        if self.direction is MetricImprovementDirection.HIGHER_IS_BETTER:
            return candidate - baseline
        return baseline - candidate


@dataclass(frozen=True)
class ComparativeMetricEvidence:
    """Same-window baseline and candidate values produced by the study owner."""

    metric_key: str
    unit: str
    baseline_value: Decimal
    candidate_value: Decimal

    def __post_init__(self) -> None:
        _require_token(self.metric_key, "ComparativeMetricEvidence.metric_key")
        _require_token(self.unit, "ComparativeMetricEvidence.unit")
        _require_finite(self.baseline_value, "ComparativeMetricEvidence.baseline_value")
        _require_finite(self.candidate_value, "ComparativeMetricEvidence.candidate_value")


@dataclass(frozen=True)
class ComparativeMetricResult:
    """Recomputed result for one governed comparative metric."""

    metric_key: str
    unit: str
    direction: MetricImprovementDirection
    baseline_value: Decimal
    candidate_value: Decimal
    improvement_delta: Decimal
    minimum_improvement_delta: Decimal
    passed: bool


@dataclass(frozen=True)
class PolicyCoefficientCriterion:
    """Pre-registered expected policy coefficient and significance contract."""

    coefficient_key: str
    target_code: str
    lag_periods: int
    expected_sign: PolicyCoefficientSign
    maximum_p_value: Decimal
    minimum_absolute_estimate: Decimal

    def __post_init__(self) -> None:
        _require_token(self.coefficient_key, "PolicyCoefficientCriterion.coefficient_key")
        _require_token(self.target_code, "PolicyCoefficientCriterion.target_code")
        _require_positive_int(self.lag_periods, "PolicyCoefficientCriterion.lag_periods")
        if not isinstance(self.expected_sign, PolicyCoefficientSign):
            raise ValueError("policy coefficient expected_sign is invalid")
        _require_finite(self.maximum_p_value, "PolicyCoefficientCriterion.maximum_p_value")
        _require_finite(
            self.minimum_absolute_estimate,
            "PolicyCoefficientCriterion.minimum_absolute_estimate",
        )
        if not Decimal("0") <= self.maximum_p_value <= Decimal("1"):
            raise ValueError("maximum_p_value must be between zero and one")
        if self.minimum_absolute_estimate < 0:
            raise ValueError("minimum_absolute_estimate cannot be negative")


@dataclass(frozen=True)
class PolicyReactionCoefficientEvidence:
    """Externally estimated coefficient with an auditable uncertainty interval."""

    coefficient_key: str
    target_code: str
    lag_periods: int
    estimate: Decimal
    standard_error: Decimal
    confidence_interval_lower: Decimal
    confidence_interval_upper: Decimal
    p_value: Decimal

    def __post_init__(self) -> None:
        _require_token(self.coefficient_key, "PolicyReactionCoefficient.coefficient_key")
        _require_token(self.target_code, "PolicyReactionCoefficient.target_code")
        _require_positive_int(self.lag_periods, "PolicyReactionCoefficient.lag_periods")
        for field_name in (
            "estimate",
            "standard_error",
            "confidence_interval_lower",
            "confidence_interval_upper",
            "p_value",
        ):
            _require_finite(
                getattr(self, field_name),
                f"PolicyReactionCoefficient.{field_name}",
            )
        if self.standard_error <= 0:
            raise ValueError("policy coefficient standard_error must be positive")
        if self.confidence_interval_lower > self.confidence_interval_upper:
            raise ValueError("policy coefficient confidence interval is reversed")
        if not self.confidence_interval_lower <= self.estimate <= self.confidence_interval_upper:
            raise ValueError("policy coefficient estimate must lie within its confidence interval")
        if not Decimal("0") <= self.p_value <= Decimal("1"):
            raise ValueError("policy coefficient p_value must be between zero and one")


@dataclass(frozen=True)
class PolicyReactionDiagnosticEvidence:
    """Same-window policy-reaction regression diagnostics."""

    sample_count: int
    adjusted_r_squared: Decimal
    residual_autocorrelation_p_value: Decimal
    heteroskedasticity_p_value: Decimal
    parameter_stability_p_value: Decimal
    condition_number: Decimal

    def __post_init__(self) -> None:
        _require_positive_int(self.sample_count, "PolicyReactionDiagnostics.sample_count")
        for field_name in (
            "adjusted_r_squared",
            "residual_autocorrelation_p_value",
            "heteroskedasticity_p_value",
            "parameter_stability_p_value",
            "condition_number",
        ):
            _require_finite(
                getattr(self, field_name),
                f"PolicyReactionDiagnostics.{field_name}",
            )
        if not Decimal("-1") <= self.adjusted_r_squared <= Decimal("1"):
            raise ValueError("adjusted_r_squared must be between minus one and one")
        for value in (
            self.residual_autocorrelation_p_value,
            self.heteroskedasticity_p_value,
            self.parameter_stability_p_value,
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError("policy diagnostic p-values must be between zero and one")
        if self.condition_number <= 0:
            raise ValueError("policy diagnostic condition_number must be positive")


@dataclass(frozen=True)
class StateModelQualificationPolicy:
    """Research-owned, versioned thresholds with no code defaults."""

    policy_version: str
    activated_at: datetime
    valid_until: datetime
    metric_criteria: tuple[ComparativeMetricCriterion, ...]
    coefficient_criteria: tuple[PolicyCoefficientCriterion, ...]
    minimum_policy_sample_count: int
    minimum_adjusted_r_squared: Decimal
    minimum_residual_autocorrelation_p_value: Decimal
    minimum_heteroskedasticity_p_value: Decimal
    minimum_parameter_stability_p_value: Decimal
    maximum_condition_number: Decimal
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "StateModelQualificationPolicy.policy_version")
        _require_aware(self.activated_at, "StateModelQualificationPolicy.activated_at")
        _require_aware(self.valid_until, "StateModelQualificationPolicy.valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("qualification policy valid_until must follow activated_at")
        metric_keys = tuple(item.metric_key for item in self.metric_criteria)
        coefficient_keys = tuple(item.coefficient_key for item in self.coefficient_criteria)
        if not metric_keys or len(metric_keys) != len(set(metric_keys)):
            raise ValueError("qualification metric criteria must be non-empty and unique")
        if frozenset(metric_keys) != REQUIRED_QUALIFICATION_METRIC_KEYS:
            raise ValueError("qualification policy must define exactly seven comparative metrics")
        if not coefficient_keys or len(coefficient_keys) != len(set(coefficient_keys)):
            raise ValueError("policy coefficient criteria must be non-empty and unique")
        _require_positive_int(
            self.minimum_policy_sample_count,
            "StateModelQualificationPolicy.minimum_policy_sample_count",
        )
        for field_name in (
            "minimum_adjusted_r_squared",
            "minimum_residual_autocorrelation_p_value",
            "minimum_heteroskedasticity_p_value",
            "minimum_parameter_stability_p_value",
            "maximum_condition_number",
        ):
            _require_finite(
                getattr(self, field_name),
                f"StateModelQualificationPolicy.{field_name}",
            )
        if not Decimal("-1") <= self.minimum_adjusted_r_squared <= Decimal("1"):
            raise ValueError("minimum_adjusted_r_squared must be between minus one and one")
        for value in (
            self.minimum_residual_autocorrelation_p_value,
            self.minimum_heteroskedasticity_p_value,
            self.minimum_parameter_stability_p_value,
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError("minimum diagnostic p-values must be between zero and one")
        if self.maximum_condition_number <= 0:
            raise ValueError("maximum_condition_number must be positive")
        _require_sha256(self.content_hash, "StateModelQualificationPolicy.content_hash")

    @property
    def calculated_content_hash(self) -> str:
        """Seal every injected comparison and diagnostic threshold."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


@dataclass(frozen=True)
class StateModelStudyPreregistration:
    """Experiment family, split, and embargo frozen before the OOS window."""

    registration_id: str
    trial_family_id: str
    trial_family_hash: str
    candidate_id: str
    candidate_version: str
    methodology: AdvancedStateMethodology
    baseline_shortfall_report_hash: str
    qualification_policy_version: str
    qualification_policy_hash: str
    oos_window_start: datetime
    oos_window_end: datetime
    split_policy_version: str
    embargo_periods: int
    registered_at: datetime
    evidence_ref: str
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "registration_id",
            "trial_family_id",
            "candidate_id",
            "candidate_version",
            "qualification_policy_version",
            "split_policy_version",
        ):
            _require_token(getattr(self, field_name), f"StateModelPreregistration.{field_name}")
        _require_sha256(self.trial_family_hash, "StateModelPreregistration.trial_family_hash")
        _require_sha256(
            self.baseline_shortfall_report_hash,
            "StateModelPreregistration.baseline_shortfall_report_hash",
        )
        _require_sha256(
            self.qualification_policy_hash,
            "StateModelPreregistration.qualification_policy_hash",
        )
        if not isinstance(self.methodology, AdvancedStateMethodology):
            raise ValueError("preregistered methodology is invalid")
        for field_name in ("oos_window_start", "oos_window_end", "registered_at"):
            _require_aware(
                getattr(self, field_name),
                f"StateModelPreregistration.{field_name}",
            )
        if self.oos_window_end <= self.oos_window_start:
            raise ValueError("preregistered OOS window_end must follow window_start")
        if self.registered_at >= self.oos_window_start:
            raise ValueError("study must be registered before the OOS window")
        if isinstance(self.embargo_periods, bool) or self.embargo_periods < 0:
            raise ValueError("preregistered embargo_periods cannot be negative")
        _require_text(self.evidence_ref, "StateModelPreregistration.evidence_ref")
        _require_sha256(self.content_hash, "StateModelPreregistration.content_hash")

    @property
    def calculated_content_hash(self) -> str:
        """Return a canonical seal over the full preregistration."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


def advanced_state_threshold_hash(
    thresholds: AdvancedStateModelAcceptanceThresholds,
) -> str:
    """Return the canonical seal used by the Research-owned S2 attestation."""

    if not isinstance(thresholds, AdvancedStateModelAcceptanceThresholds):
        raise TypeError("thresholds must be AdvancedStateModelAcceptanceThresholds")
    return _canonical_hash(thresholds)


def advanced_state_pit_manifest_canonical_hash(
    pit_manifest: StateModelPITManifestEvidence,
) -> str:
    """Seal the full PIT manifest rather than trusting its owner-declared hash alone."""

    if not isinstance(pit_manifest, StateModelPITManifestEvidence):
        raise TypeError("pit_manifest must be StateModelPITManifestEvidence")
    return _canonical_hash(pit_manifest)


def external_artifact_attestation_canonical_hash(
    artifact_attestation: ExternalArtifactAttestation,
) -> str:
    """Seal the independent artifact attestation, including its evidence clock."""

    if not isinstance(artifact_attestation, ExternalArtifactAttestation):
        raise TypeError("artifact_attestation must be ExternalArtifactAttestation")
    return _canonical_hash(artifact_attestation)


@dataclass(frozen=True, init=False)
class AdvancedStateModelAssessmentAttestation:
    """Research-owned, sealed projection of one exact S2 assessment graph."""

    assessment_id: str
    status: AdvancedStateModelAssessmentStatus
    blockers: tuple[AdvancedStateModelBlockerCode, ...]
    assessed_at: datetime
    candidate_id: str
    candidate_version: str
    candidate_evidence_hash: str
    methodology: AdvancedStateMethodology
    baseline_shortfall_specification_version: str
    baseline_shortfall_evaluation_id: str
    baseline_shortfall_report_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    pit_manifest_canonical_hash: str
    pit_manifest_as_of_time: datetime
    pit_manifest_valid_until: datetime
    pit_manifest_is_verified: bool
    pit_manifest_is_complete: bool
    pit_manifest_coverage_ratio: Decimal
    pit_manifest_missing_count: int
    pit_manifest_estimated_count: int
    pit_manifest_unknown_count: int
    label_protocol_version: str
    label_stability_evidence_hash: str
    artifact_id: str
    artifact_code_version: str
    artifact_parameter_version: str
    artifact_parameter_hash: str
    artifact_hash: str
    artifact_attestation_hash: str
    artifact_attestation_observed_at: datetime
    artifact_attestation_valid_until: datetime
    artifact_attestation_verified: bool
    artifact_attestation_evidence_ref: str
    threshold_version: str
    threshold_hash: str
    evidence_ref: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    content_hash: str = field(init=False)

    def __new__(cls) -> AdvancedStateModelAssessmentAttestation:
        """Reject direct minting; the public replay factory is the sole entry point."""

        raise TypeError("S2 assessment attestations must be minted by the replay gate")

    def __post_init__(self) -> None:
        for field_name in (
            "assessment_id",
            "candidate_id",
            "candidate_version",
            "baseline_shortfall_specification_version",
            "baseline_shortfall_evaluation_id",
            "pit_manifest_id",
            "label_protocol_version",
            "artifact_id",
            "artifact_code_version",
            "artifact_parameter_version",
            "threshold_version",
        ):
            _require_token(
                getattr(self, field_name),
                f"AdvancedAssessmentAttestation.{field_name}",
            )
        for field_name in (
            "candidate_evidence_hash",
            "baseline_shortfall_report_hash",
            "pit_manifest_hash",
            "pit_manifest_canonical_hash",
            "label_stability_evidence_hash",
            "artifact_parameter_hash",
            "artifact_hash",
            "artifact_attestation_hash",
            "threshold_hash",
        ):
            _require_sha256(
                getattr(self, field_name),
                f"AdvancedAssessmentAttestation.{field_name}",
            )
        if not isinstance(self.status, AdvancedStateModelAssessmentStatus):
            raise ValueError("advanced assessment attestation status is invalid")
        if not isinstance(self.methodology, AdvancedStateMethodology):
            raise ValueError("advanced assessment attestation methodology is invalid")
        if len(self.blockers) != len(set(self.blockers)) or any(
            not isinstance(blocker, AdvancedStateModelBlockerCode) for blocker in self.blockers
        ):
            raise ValueError("advanced assessment attestation blockers are invalid")
        _require_aware(self.assessed_at, "AdvancedAssessmentAttestation.assessed_at")
        for field_name in (
            "pit_manifest_as_of_time",
            "pit_manifest_valid_until",
            "artifact_attestation_observed_at",
            "artifact_attestation_valid_until",
        ):
            _require_aware(
                getattr(self, field_name),
                f"AdvancedAssessmentAttestation.{field_name}",
            )
        if self.pit_manifest_valid_until <= self.pit_manifest_as_of_time:
            raise ValueError("attested PIT manifest validity interval is reversed")
        if self.artifact_attestation_valid_until <= self.artifact_attestation_observed_at:
            raise ValueError("attested artifact validity interval is reversed")
        if not isinstance(self.pit_manifest_is_verified, bool) or not isinstance(
            self.pit_manifest_is_complete, bool
        ):
            raise ValueError("attested PIT verification fields must be booleans")
        if not isinstance(self.artifact_attestation_verified, bool):
            raise ValueError("attested artifact verified must be a boolean")
        _require_finite(
            self.pit_manifest_coverage_ratio,
            "AdvancedAssessmentAttestation.pit_manifest_coverage_ratio",
        )
        if not Decimal("0") <= self.pit_manifest_coverage_ratio <= Decimal("1"):
            raise ValueError("attested PIT coverage ratio must be between zero and one")
        for field_name in (
            "pit_manifest_missing_count",
            "pit_manifest_estimated_count",
            "pit_manifest_unknown_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"AdvancedAssessmentAttestation.{field_name} cannot be negative")
        _require_text(
            self.artifact_attestation_evidence_ref,
            "AdvancedAssessmentAttestation.artifact_attestation_evidence_ref",
        )
        _require_text(self.evidence_ref, "AdvancedAssessmentAttestation.evidence_ref")
        if self.status is AdvancedStateModelAssessmentStatus.ACCEPTED:
            complete_pit = (
                self.pit_manifest_is_verified
                and self.pit_manifest_is_complete
                and self.pit_manifest_coverage_ratio == Decimal("1")
                and self.pit_manifest_missing_count == 0
                and self.pit_manifest_estimated_count == 0
                and self.pit_manifest_unknown_count == 0
            )
            if self.blockers or not complete_pit or not self.artifact_attestation_verified:
                raise ValueError("accepted S2 attestation requires replay-verified dependencies")
        elif not self.blockers:
            raise ValueError("blocked S2 attestation requires replayed gate blockers")
        if (
            self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_replace_regime is not True
        ):
            raise ValueError("advanced assessment attestation must remain research-only")
        object.__setattr__(self, "content_hash", self.calculated_content_hash)

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical seal over the complete S2 dependency graph."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


def _mint_advanced_state_model_assessment_attestation(
    *,
    assessment_id: str,
    assessment: AdvancedStateModelAssessment,
    candidate: AdvancedStateModelCandidateEvidence,
    baseline_shortfall: BaselineShortfallReport,
    pit_manifest: StateModelPITManifestEvidence,
    artifact_attestation: ExternalArtifactAttestation,
    thresholds: AdvancedStateModelAcceptanceThresholds,
    evidence_ref: str,
) -> AdvancedStateModelAssessmentAttestation:
    """Mint one attestation only from the immediately replayed S2 graph."""

    artifact = candidate.artifact
    label = candidate.label_protocol
    instance = object.__new__(AdvancedStateModelAssessmentAttestation)
    values: tuple[tuple[str, object], ...] = (
        ("assessment_id", assessment_id),
        ("status", assessment.status),
        ("blockers", assessment.blockers),
        ("assessed_at", assessment.assessed_at),
        ("candidate_id", candidate.candidate_id),
        ("candidate_version", candidate.candidate_version),
        ("candidate_evidence_hash", candidate.evidence_hash),
        ("methodology", candidate.methodology),
        ("baseline_shortfall_specification_version", baseline_shortfall.specification_version),
        ("baseline_shortfall_evaluation_id", baseline_shortfall.evaluation_id),
        ("baseline_shortfall_report_hash", baseline_shortfall.content_hash),
        ("pit_manifest_id", pit_manifest.manifest_id),
        ("pit_manifest_hash", pit_manifest.manifest_hash),
        (
            "pit_manifest_canonical_hash",
            advanced_state_pit_manifest_canonical_hash(pit_manifest),
        ),
        ("pit_manifest_as_of_time", pit_manifest.as_of_time),
        ("pit_manifest_valid_until", pit_manifest.valid_until),
        ("pit_manifest_is_verified", pit_manifest.is_verified),
        ("pit_manifest_is_complete", pit_manifest.is_complete),
        ("pit_manifest_coverage_ratio", pit_manifest.coverage_ratio),
        ("pit_manifest_missing_count", pit_manifest.missing_count),
        ("pit_manifest_estimated_count", pit_manifest.estimated_count),
        ("pit_manifest_unknown_count", pit_manifest.unknown_count),
        ("label_protocol_version", label.protocol_version),
        ("label_stability_evidence_hash", label.stability_evidence_hash),
        ("artifact_id", artifact.artifact_id),
        ("artifact_code_version", artifact.code_version),
        ("artifact_parameter_version", artifact.parameter_version),
        ("artifact_parameter_hash", artifact.parameter_hash),
        ("artifact_hash", artifact.artifact_hash),
        (
            "artifact_attestation_hash",
            external_artifact_attestation_canonical_hash(artifact_attestation),
        ),
        ("artifact_attestation_observed_at", artifact_attestation.observed_at),
        ("artifact_attestation_valid_until", artifact_attestation.valid_until),
        ("artifact_attestation_verified", artifact_attestation.verified),
        ("artifact_attestation_evidence_ref", artifact_attestation.evidence_ref),
        ("threshold_version", thresholds.threshold_version),
        ("threshold_hash", advanced_state_threshold_hash(thresholds)),
        ("evidence_ref", evidence_ref),
        ("research_only", True),
        ("must_not_use_for_decision", True),
        ("must_not_replace_regime", True),
    )
    for name, value in values:
        object.__setattr__(instance, name, value)
    object.__setattr__(instance, "content_hash", instance.calculated_content_hash)
    instance.__post_init__()
    return instance


def attest_advanced_state_model_assessment(
    *,
    assessment_id: str,
    candidate: AdvancedStateModelCandidateEvidence,
    baseline_shortfall: BaselineShortfallReport,
    pit_manifest: StateModelPITManifestEvidence,
    artifact_attestation: ExternalArtifactAttestation,
    thresholds: AdvancedStateModelAcceptanceThresholds,
    evaluated_at: datetime,
    evidence_ref: str,
) -> AdvancedStateModelAssessmentAttestation:
    """Replay S2 and seal its exact PIT, artifact, threshold, and evidence graph."""

    assessment = evaluate_advanced_state_model_evidence(
        candidate=candidate,
        baseline_shortfall=baseline_shortfall,
        pit_manifest=pit_manifest,
        artifact_attestation=artifact_attestation,
        thresholds=thresholds,
        evaluated_at=evaluated_at,
    )
    return _mint_advanced_state_model_assessment_attestation(
        assessment_id=assessment_id,
        assessment=assessment,
        candidate=candidate,
        baseline_shortfall=baseline_shortfall,
        pit_manifest=pit_manifest,
        artifact_attestation=artifact_attestation,
        thresholds=thresholds,
        evidence_ref=evidence_ref,
    )


@dataclass(frozen=True)
class StateModelDerivedMetricBundle:
    """Sealed owner bundle for the three metrics not present on the candidate."""

    bundle_id: str
    bundle_version: str
    provider: str
    candidate_id: str
    candidate_version: str
    candidate_evidence_hash: str
    label_protocol_version: str
    label_stability_evidence_hash: str
    decision_loss_utility: Decimal
    complexity_score: Decimal
    label_stability_score: Decimal
    evaluated_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "bundle_id",
            "bundle_version",
            "candidate_id",
            "candidate_version",
            "label_protocol_version",
        ):
            _require_token(getattr(self, field_name), f"DerivedMetricBundle.{field_name}")
        _require_text(self.provider, "DerivedMetricBundle.provider")
        for field_name in (
            "candidate_evidence_hash",
            "label_stability_evidence_hash",
        ):
            _require_sha256(getattr(self, field_name), f"DerivedMetricBundle.{field_name}")
        for field_name in (
            "decision_loss_utility",
            "complexity_score",
            "label_stability_score",
        ):
            _require_finite(getattr(self, field_name), f"DerivedMetricBundle.{field_name}")
        if not Decimal("0") <= self.label_stability_score <= Decimal("1"):
            raise ValueError("derived label_stability_score must be between zero and one")
        _require_aware(self.evaluated_at, "DerivedMetricBundle.evaluated_at")
        _require_aware(self.valid_until, "DerivedMetricBundle.valid_until")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("derived metric bundle valid_until must follow evaluated_at")
        _require_text(self.evidence_ref, "DerivedMetricBundle.evidence_ref")
        object.__setattr__(self, "content_hash", self.calculated_content_hash)

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical seal over identities, labels, and all three values."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))

    @property
    def metric_values(self) -> dict[str, Decimal]:
        """Return the exact metric values rebound against the study payload."""

        return {
            "decision_loss_utility": self.decision_loss_utility,
            "complexity_score": self.complexity_score,
            "label_stability_score": self.label_stability_score,
        }


@dataclass(frozen=True)
class StateModelComparativeStudyEvidence:
    """Owner-produced same-window comparison and policy-reaction evidence."""

    study_id: str = field(init=False)
    candidate_id: str
    candidate_version: str
    candidate_evidence_hash: str
    artifact_hash: str
    advanced_assessment_id: str
    advanced_assessment_hash: str
    advanced_pit_manifest_canonical_hash: str
    advanced_artifact_attestation_hash: str
    advanced_threshold_hash: str
    derived_metric_bundle_id: str
    derived_metric_bundle_version: str
    derived_metric_bundle_hash: str
    baseline_shortfall_specification_version: str
    baseline_shortfall_evaluation_id: str
    baseline_shortfall_report_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    label_protocol_version: str
    label_stability_evidence_hash: str
    preregistration_id: str
    preregistration_hash: str
    trial_family_id: str
    trial_family_hash: str
    split_policy_version: str
    embargo_periods: int
    qualification_policy_version: str
    qualification_policy_hash: str
    policy_reaction_specification_version: str
    policy_reaction_evidence_hash: str
    oos_window_start: datetime
    oos_window_end: datetime
    sample_count: int
    metrics: tuple[ComparativeMetricEvidence, ...]
    policy_coefficients: tuple[PolicyReactionCoefficientEvidence, ...]
    policy_diagnostics: PolicyReactionDiagnosticEvidence
    evaluated_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "candidate_version",
            "advanced_assessment_id",
            "derived_metric_bundle_id",
            "derived_metric_bundle_version",
            "baseline_shortfall_specification_version",
            "baseline_shortfall_evaluation_id",
            "pit_manifest_id",
            "label_protocol_version",
            "preregistration_id",
            "trial_family_id",
            "split_policy_version",
            "qualification_policy_version",
            "policy_reaction_specification_version",
        ):
            _require_token(getattr(self, field_name), f"ComparativeStudy.{field_name}")
        for field_name in (
            "candidate_evidence_hash",
            "artifact_hash",
            "advanced_assessment_hash",
            "advanced_pit_manifest_canonical_hash",
            "advanced_artifact_attestation_hash",
            "advanced_threshold_hash",
            "derived_metric_bundle_hash",
            "baseline_shortfall_report_hash",
            "pit_manifest_hash",
            "label_stability_evidence_hash",
            "preregistration_hash",
            "trial_family_hash",
            "qualification_policy_hash",
            "policy_reaction_evidence_hash",
        ):
            _require_sha256(getattr(self, field_name), f"ComparativeStudy.{field_name}")
        for field_name in (
            "oos_window_start",
            "oos_window_end",
            "evaluated_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), f"ComparativeStudy.{field_name}")
        if self.oos_window_end <= self.oos_window_start:
            raise ValueError("comparative study OOS window_end must follow window_start")
        if self.evaluated_at < self.oos_window_end:
            raise ValueError("comparative study cannot be evaluated before its OOS window ends")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("comparative study valid_until must follow evaluated_at")
        _require_positive_int(self.sample_count, "ComparativeStudy.sample_count")
        if isinstance(self.embargo_periods, bool) or self.embargo_periods < 0:
            raise ValueError("comparative study embargo_periods cannot be negative")
        metric_keys = tuple(item.metric_key for item in self.metrics)
        coefficient_keys = tuple(item.coefficient_key for item in self.policy_coefficients)
        if not metric_keys or len(metric_keys) != len(set(metric_keys)):
            raise ValueError("comparative study metrics must be non-empty and unique")
        if not coefficient_keys or len(coefficient_keys) != len(set(coefficient_keys)):
            raise ValueError("policy coefficients must be non-empty and unique")
        _require_text(self.evidence_ref, "ComparativeStudy.evidence_ref")
        object.__setattr__(self, "study_id", self.calculated_study_id)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        _require_token(self.study_id, "ComparativeStudy.study_id")
        _require_sha256(self.content_hash, "ComparativeStudy.content_hash")

    @property
    def calculated_body_hash(self) -> str:
        """Seal the full study body independently of its derived identity and seal."""

        return _canonical_hash(
            self,
            excluded_fields=frozenset({"study_id", "content_hash"}),
        )

    @property
    def calculated_study_id(self) -> str:
        """Derive a collision-resistant immutable identity from the full study body."""

        return f"r6-state-model-study-sha256-{self.calculated_body_hash}"

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical digest over all study identities and values."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


@dataclass(frozen=True, init=False)
class StateModelQualificationAssessment:
    """Canonical research-only evidence for a later human promotion review."""

    status: StateModelQualificationStatus
    study_id: str
    candidate_id: str | None
    candidate_version: str | None
    study_hash: str | None
    preregistration_hash: str | None
    baseline_shortfall_report_hash: str | None
    candidate_evidence_hash: str | None
    advanced_assessment_hash: str | None
    pit_manifest_canonical_hash: str | None
    artifact_attestation_hash: str | None
    advanced_threshold_hash: str | None
    derived_metric_bundle_hash: str | None
    policy_hash: str | None
    assessed_at: datetime
    metric_results: tuple[ComparativeMetricResult, ...]
    blockers: tuple[StateModelQualificationBlockerCode, ...]
    may_request_promotion_review: bool
    promotion_decision_present: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    content_hash: str = field(init=False)

    def __new__(cls) -> StateModelQualificationAssessment:
        """Reject direct construction outside the module-private qualification gate."""

        raise TypeError("qualification assessments must be minted by the qualification gate")

    def __post_init__(self) -> None:
        if not isinstance(self.status, StateModelQualificationStatus):
            raise ValueError("state-model qualification status is invalid")
        _require_token(self.study_id, "StateModelQualificationAssessment.study_id")
        if self.candidate_id is not None:
            _require_token(
                self.candidate_id,
                "StateModelQualificationAssessment.candidate_id",
            )
        if self.candidate_version is not None:
            _require_token(
                self.candidate_version,
                "StateModelQualificationAssessment.candidate_version",
            )
        _require_aware(self.assessed_at, "StateModelQualificationAssessment.assessed_at")
        for field_name in (
            "study_hash",
            "preregistration_hash",
            "baseline_shortfall_report_hash",
            "candidate_evidence_hash",
            "advanced_assessment_hash",
            "pit_manifest_canonical_hash",
            "artifact_attestation_hash",
            "advanced_threshold_hash",
            "derived_metric_bundle_hash",
            "policy_hash",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_sha256(value, f"StateModelQualificationAssessment.{field_name}")
        _require_sha256(self.content_hash, "StateModelQualificationAssessment.content_hash")
        if len(self.blockers) != len(set(self.blockers)) or any(
            not isinstance(blocker, StateModelQualificationBlockerCode) for blocker in self.blockers
        ):
            raise ValueError("qualification assessment blockers must be unique stable codes")
        metric_keys = tuple(result.metric_key for result in self.metric_results)
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("qualification assessment metric results must be uniquely keyed")
        if self.status is StateModelQualificationStatus.EVIDENCE_COMPLETE:
            if self.blockers or not self.may_request_promotion_review:
                raise ValueError("complete qualification evidence cannot contain blockers")
            if (
                frozenset(metric_keys) != REQUIRED_QUALIFICATION_METRIC_KEYS
                or len(metric_keys) != len(REQUIRED_QUALIFICATION_METRIC_KEYS)
                or any(not result.passed for result in self.metric_results)
            ):
                raise ValueError("complete qualification evidence requires seven passed metrics")
            required = (
                self.candidate_id,
                self.candidate_version,
                self.study_hash,
                self.preregistration_hash,
                self.baseline_shortfall_report_hash,
                self.candidate_evidence_hash,
                self.advanced_assessment_hash,
                self.pit_manifest_canonical_hash,
                self.artifact_attestation_hash,
                self.advanced_threshold_hash,
                self.derived_metric_bundle_hash,
                self.policy_hash,
            )
            if any(value is None for value in required):
                raise ValueError("complete qualification evidence requires exact references")
        elif not self.blockers or self.may_request_promotion_review:
            raise ValueError("blocked qualification evidence requires blockers")
        if (
            self.promotion_decision_present is not False
            or self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_replace_regime is not True
        ):
            raise ValueError(
                "qualification evidence cannot authorize a decision or Regime replacement"
            )
        if self.content_hash.lower() != self.calculated_content_hash:
            raise ValueError("state-model qualification assessment content_hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return a digest sealing the complete qualification outcome."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


def _mint_state_model_qualification_assessment(
    *,
    status: StateModelQualificationStatus,
    study_id: str,
    candidate_id: str | None,
    candidate_version: str | None,
    study_hash: str | None,
    preregistration_hash: str | None,
    baseline_shortfall_report_hash: str | None,
    candidate_evidence_hash: str | None,
    advanced_assessment_hash: str | None,
    pit_manifest_canonical_hash: str | None,
    artifact_attestation_hash: str | None,
    advanced_threshold_hash: str | None,
    derived_metric_bundle_hash: str | None,
    policy_hash: str | None,
    assessed_at: datetime,
    metric_results: tuple[ComparativeMetricResult, ...],
    blockers: tuple[StateModelQualificationBlockerCode, ...],
    may_request_promotion_review: bool,
) -> StateModelQualificationAssessment:
    """Mint one immutable outcome at the module-private qualification boundary."""

    instance = object.__new__(StateModelQualificationAssessment)
    values: tuple[tuple[str, object], ...] = (
        ("status", status),
        ("study_id", study_id),
        ("candidate_id", candidate_id),
        ("candidate_version", candidate_version),
        ("study_hash", study_hash),
        ("preregistration_hash", preregistration_hash),
        ("baseline_shortfall_report_hash", baseline_shortfall_report_hash),
        ("candidate_evidence_hash", candidate_evidence_hash),
        ("advanced_assessment_hash", advanced_assessment_hash),
        ("pit_manifest_canonical_hash", pit_manifest_canonical_hash),
        ("artifact_attestation_hash", artifact_attestation_hash),
        ("advanced_threshold_hash", advanced_threshold_hash),
        ("derived_metric_bundle_hash", derived_metric_bundle_hash),
        ("policy_hash", policy_hash),
        ("assessed_at", assessed_at),
        ("metric_results", metric_results),
        ("blockers", blockers),
        ("may_request_promotion_review", may_request_promotion_review),
        ("promotion_decision_present", False),
        ("research_only", True),
        ("must_not_use_for_decision", True),
        ("must_not_replace_regime", True),
    )
    for name, value in values:
        object.__setattr__(instance, name, value)
    object.__setattr__(instance, "content_hash", instance.calculated_content_hash)
    instance.__post_init__()
    return instance


def _candidate_metric_values(
    candidate: AdvancedStateModelCandidateEvidence,
) -> dict[str, Decimal]:
    metrics = candidate.oos_metrics
    return {
        "transition_accuracy": metrics.transition_accuracy,
        "log_loss": metrics.log_loss,
        "calibration_error": metrics.calibration_error,
        "duration_mae_periods": metrics.duration_mae_periods,
    }


def _build_assessment(
    *,
    study_id: str,
    assessed_at: datetime,
    study: StateModelComparativeStudyEvidence | None,
    preregistration: StateModelStudyPreregistration | None,
    baseline_shortfall: BaselineShortfallReport | None,
    candidate: AdvancedStateModelCandidateEvidence | None,
    advanced_assessment: AdvancedStateModelAssessmentAttestation | None,
    derived_metric_bundle: StateModelDerivedMetricBundle | None,
    policy: StateModelQualificationPolicy | None,
    metric_results: tuple[ComparativeMetricResult, ...],
    blockers: list[StateModelQualificationBlockerCode],
) -> StateModelQualificationAssessment:
    unique_blockers = tuple(dict.fromkeys(blockers))
    status = (
        StateModelQualificationStatus.BLOCKED
        if unique_blockers
        else StateModelQualificationStatus.EVIDENCE_COMPLETE
    )
    return _mint_state_model_qualification_assessment(
        status=status,
        study_id=study_id,
        candidate_id=(
            study.candidate_id
            if study is not None
            else (candidate.candidate_id if candidate is not None else None)
        ),
        candidate_version=(
            study.candidate_version
            if study is not None
            else (candidate.candidate_version if candidate is not None else None)
        ),
        study_hash=(study.content_hash if study is not None else None),
        preregistration_hash=(
            preregistration.content_hash if preregistration is not None else None
        ),
        baseline_shortfall_report_hash=(
            baseline_shortfall.content_hash if baseline_shortfall is not None else None
        ),
        candidate_evidence_hash=(candidate.evidence_hash if candidate is not None else None),
        advanced_assessment_hash=(
            advanced_assessment.content_hash if advanced_assessment is not None else None
        ),
        pit_manifest_canonical_hash=(
            advanced_assessment.pit_manifest_canonical_hash
            if advanced_assessment is not None
            else None
        ),
        artifact_attestation_hash=(
            advanced_assessment.artifact_attestation_hash
            if advanced_assessment is not None
            else None
        ),
        advanced_threshold_hash=(
            advanced_assessment.threshold_hash if advanced_assessment is not None else None
        ),
        derived_metric_bundle_hash=(
            derived_metric_bundle.content_hash if derived_metric_bundle is not None else None
        ),
        policy_hash=(policy.content_hash if policy is not None else None),
        assessed_at=assessed_at,
        metric_results=metric_results,
        blockers=unique_blockers,
        may_request_promotion_review=not unique_blockers,
    )


def missing_state_model_qualification_assessment(
    *,
    study_id: str,
    assessed_at: datetime,
    blocker: StateModelQualificationBlockerCode,
) -> StateModelQualificationAssessment:
    """Build a sealed fail-closed result when ID-only collection cannot begin."""

    _require_token(study_id, "study_id")
    _require_aware(assessed_at, "assessed_at")
    return _build_assessment(
        study_id=study_id,
        assessed_at=assessed_at,
        study=None,
        preregistration=None,
        baseline_shortfall=None,
        candidate=None,
        advanced_assessment=None,
        derived_metric_bundle=None,
        policy=None,
        metric_results=(),
        blockers=[blocker],
    )


def evaluate_state_model_qualification(
    *,
    candidate: AdvancedStateModelCandidateEvidence | None,
    advanced_assessment: (
        AdvancedStateModelAssessmentAttestation | AdvancedStateModelAssessment | None
    ),
    derived_metric_bundle: StateModelDerivedMetricBundle | None,
    baseline_shortfall: BaselineShortfallReport | None,
    preregistration: StateModelStudyPreregistration | None,
    study: StateModelComparativeStudyEvidence,
    policy: StateModelQualificationPolicy | None,
    assessed_at: datetime,
) -> StateModelQualificationAssessment:
    """Recompute all exact bindings and permit only manual promotion review."""

    _require_aware(assessed_at, "assessed_at")
    blockers: list[StateModelQualificationBlockerCode] = []
    if (
        study.content_hash.lower() != study.calculated_content_hash
        or study.study_id != study.calculated_study_id
    ):
        blockers.append(StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH)
    if study.evaluated_at > assessed_at:
        blockers.append(StateModelQualificationBlockerCode.STUDY_FROM_FUTURE)
    if study.valid_until <= assessed_at:
        blockers.append(StateModelQualificationBlockerCode.STUDY_STALE)

    if preregistration is None:
        blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_MISSING)
    else:
        if preregistration.content_hash.lower() != preregistration.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_HASH_MISMATCH)
        preregistration_binding = (
            preregistration.registration_id,
            preregistration.content_hash.lower(),
            preregistration.trial_family_id,
            preregistration.trial_family_hash.lower(),
            preregistration.split_policy_version,
            preregistration.embargo_periods,
            preregistration.candidate_id,
            preregistration.candidate_version,
            preregistration.baseline_shortfall_report_hash.lower(),
            preregistration.qualification_policy_version,
            preregistration.qualification_policy_hash.lower(),
            preregistration.oos_window_start,
            preregistration.oos_window_end,
        )
        study_binding = (
            study.preregistration_id,
            study.preregistration_hash.lower(),
            study.trial_family_id,
            study.trial_family_hash.lower(),
            study.split_policy_version,
            study.embargo_periods,
            study.candidate_id,
            study.candidate_version,
            study.baseline_shortfall_report_hash.lower(),
            study.qualification_policy_version,
            study.qualification_policy_hash.lower(),
            study.oos_window_start,
            study.oos_window_end,
        )
        if preregistration_binding != study_binding:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH)

    if candidate is None:
        blockers.append(StateModelQualificationBlockerCode.CANDIDATE_MISSING)
    else:
        if candidate.evidence_hash.lower() != candidate.calculated_evidence_hash:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_HASH_MISMATCH)
        if candidate.valid_until <= assessed_at:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_EVIDENCE_STALE)
        if candidate.lifecycle_status is StateModelLifecycleStatus.RETIRED:
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_RETIRED)
        if (
            study.candidate_id != candidate.candidate_id
            or study.candidate_version != candidate.candidate_version
            or study.candidate_evidence_hash.lower() != candidate.evidence_hash.lower()
            or study.artifact_hash.lower() != candidate.artifact.artifact_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.CANDIDATE_BINDING_MISMATCH)
        if (
            study.pit_manifest_id != candidate.pit_manifest_id
            or study.pit_manifest_hash.lower() != candidate.pit_manifest_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.PIT_BINDING_MISMATCH)
        label = candidate.label_protocol
        if (
            study.label_protocol_version != label.protocol_version
            or study.label_stability_evidence_hash.lower() != label.stability_evidence_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.LABEL_BINDING_MISMATCH)
        if not label.is_stable or label.drift_detected:
            blockers.append(StateModelQualificationBlockerCode.LABEL_PROTOCOL_UNSTABLE)
        policy_reaction = candidate.policy_reaction
        if (
            policy_reaction is None
            or study.policy_reaction_specification_version != policy_reaction.specification_version
            or study.policy_reaction_evidence_hash.lower() != policy_reaction.evidence_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_REACTION_BINDING_MISMATCH)
        if preregistration is not None and preregistration.methodology is not candidate.methodology:
            blockers.append(StateModelQualificationBlockerCode.PREREGISTRATION_BINDING_MISMATCH)
        candidate_times = (
            candidate.artifact.produced_at,
            candidate.label_protocol.verified_at,
            candidate.state_distribution.observed_at,
            candidate.transition_matrix.observed_at,
            candidate.oos_metrics.evaluated_at,
            candidate.baseline_comparison.compared_at,
        )
        if any(value > study.evaluated_at for value in candidate_times):
            blockers.append(StateModelQualificationBlockerCode.EVIDENCE_TIMELINE_INVALID)

    if advanced_assessment is None:
        blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_MISSING)
    elif not isinstance(advanced_assessment, AdvancedStateModelAssessmentAttestation):
        blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
    else:
        if advanced_assessment.content_hash.lower() != advanced_assessment.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_HASH_MISMATCH)
        if (
            study.advanced_assessment_id != advanced_assessment.assessment_id
            or study.advanced_assessment_hash.lower() != advanced_assessment.content_hash.lower()
            or study.advanced_pit_manifest_canonical_hash.lower()
            != advanced_assessment.pit_manifest_canonical_hash.lower()
            or study.advanced_artifact_attestation_hash.lower()
            != advanced_assessment.artifact_attestation_hash.lower()
            or study.advanced_threshold_hash.lower() != advanced_assessment.threshold_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if (
            advanced_assessment.status is not AdvancedStateModelAssessmentStatus.ACCEPTED
            or advanced_assessment.blockers
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_GATE_NOT_ACCEPTED)
        if advanced_assessment.assessed_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.EVIDENCE_TIMELINE_INVALID)
        if candidate is not None and (
            advanced_assessment.candidate_id != candidate.candidate_id
            or advanced_assessment.candidate_version != candidate.candidate_version
            or advanced_assessment.candidate_evidence_hash.lower()
            != candidate.evidence_hash.lower()
            or advanced_assessment.methodology is not candidate.methodology
            or advanced_assessment.artifact_id != candidate.artifact.artifact_id
            or advanced_assessment.artifact_code_version != candidate.artifact.code_version
            or advanced_assessment.artifact_parameter_version
            != candidate.artifact.parameter_version
            or advanced_assessment.artifact_parameter_hash.lower()
            != candidate.artifact.parameter_hash.lower()
            or advanced_assessment.artifact_hash.lower() != candidate.artifact.artifact_hash.lower()
            or advanced_assessment.pit_manifest_id != candidate.pit_manifest_id
            or advanced_assessment.pit_manifest_hash.lower() != candidate.pit_manifest_hash.lower()
            or not advanced_assessment.pit_manifest_is_verified
            or not advanced_assessment.pit_manifest_is_complete
            or advanced_assessment.pit_manifest_coverage_ratio != Decimal("1")
            or advanced_assessment.pit_manifest_missing_count != 0
            or advanced_assessment.pit_manifest_estimated_count != 0
            or advanced_assessment.pit_manifest_unknown_count != 0
            or advanced_assessment.label_protocol_version
            != candidate.label_protocol.protocol_version
            or advanced_assessment.label_stability_evidence_hash.lower()
            != candidate.label_protocol.stability_evidence_hash.lower()
            or advanced_assessment.threshold_version != candidate.acceptance_threshold_version
            or not advanced_assessment.artifact_attestation_verified
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if (
            advanced_assessment.pit_manifest_as_of_time > advanced_assessment.assessed_at
            or advanced_assessment.pit_manifest_valid_until <= advanced_assessment.assessed_at
            or advanced_assessment.artifact_attestation_observed_at
            > advanced_assessment.assessed_at
            or advanced_assessment.artifact_attestation_valid_until
            <= advanced_assessment.assessed_at
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)
        if baseline_shortfall is not None and (
            advanced_assessment.baseline_shortfall_specification_version
            != baseline_shortfall.specification_version
            or advanced_assessment.baseline_shortfall_evaluation_id
            != baseline_shortfall.evaluation_id
            or advanced_assessment.baseline_shortfall_report_hash.lower()
            != baseline_shortfall.content_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_BINDING_MISMATCH)

    if derived_metric_bundle is None:
        blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_MISSING)
    elif not isinstance(derived_metric_bundle, StateModelDerivedMetricBundle):
        blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH)
    else:
        if (
            derived_metric_bundle.content_hash.lower()
            != derived_metric_bundle.calculated_content_hash
        ):
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_HASH_MISMATCH)
        if (
            study.derived_metric_bundle_id != derived_metric_bundle.bundle_id
            or study.derived_metric_bundle_version != derived_metric_bundle.bundle_version
            or study.derived_metric_bundle_hash.lower()
            != derived_metric_bundle.content_hash.lower()
        ):
            blockers.append(
                StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH
            )
        if derived_metric_bundle.evaluated_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_FROM_FUTURE)
        if derived_metric_bundle.valid_until <= assessed_at:
            blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_STALE)
        if candidate is not None and (
            derived_metric_bundle.candidate_id != candidate.candidate_id
            or derived_metric_bundle.candidate_version != candidate.candidate_version
            or derived_metric_bundle.candidate_evidence_hash.lower()
            != candidate.evidence_hash.lower()
            or derived_metric_bundle.label_protocol_version
            != candidate.label_protocol.protocol_version
            or derived_metric_bundle.label_stability_evidence_hash.lower()
            != candidate.label_protocol.stability_evidence_hash.lower()
        ):
            blockers.append(
                StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH
            )

    if baseline_shortfall is None:
        blockers.append(StateModelQualificationBlockerCode.BASELINE_SHORTFALL_MISSING)
    else:
        if baseline_shortfall.content_hash.lower() != baseline_shortfall.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.BASELINE_REPORT_HASH_MISMATCH)
        if (
            baseline_shortfall.decision is not BaselineShortfallDecision.PROVEN
            or not baseline_shortfall.can_propose_advanced_model_research
            or baseline_shortfall.evidence_state is not BaselineEvidenceState.VERIFIED
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_SHORTFALL_NOT_PROVEN)
        if baseline_shortfall.evidence_evaluated_at > study.evaluated_at:
            blockers.append(StateModelQualificationBlockerCode.BASELINE_EVIDENCE_FROM_FUTURE)
        if (
            baseline_shortfall.evidence_valid_until is None
            or baseline_shortfall.evidence_valid_until <= assessed_at
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_EVIDENCE_STALE)
        if (
            study.baseline_shortfall_specification_version
            != baseline_shortfall.specification_version
            or study.baseline_shortfall_evaluation_id != baseline_shortfall.evaluation_id
            or study.baseline_shortfall_report_hash.lower()
            != baseline_shortfall.content_hash.lower()
        ):
            blockers.append(StateModelQualificationBlockerCode.BASELINE_REPORT_HASH_MISMATCH)
        if candidate is not None:
            comparison = candidate.baseline_comparison
            if (
                comparison.shortfall_specification_version
                != baseline_shortfall.specification_version
                or comparison.shortfall_evaluation_id != baseline_shortfall.evaluation_id
                or comparison.shortfall_report_hash.lower()
                != baseline_shortfall.content_hash.lower()
                or comparison.baseline_key != baseline_shortfall.baseline_key
                or comparison.baseline_version != baseline_shortfall.baseline_version
                or candidate.pit_manifest_id != baseline_shortfall.pit_manifest_id
            ):
                blockers.append(StateModelQualificationBlockerCode.PIT_BINDING_MISMATCH)

    if policy is None:
        blockers.append(StateModelQualificationBlockerCode.POLICY_MISSING)
        metric_results: tuple[ComparativeMetricResult, ...] = ()
    else:
        if policy.content_hash.lower() != policy.calculated_content_hash:
            blockers.append(StateModelQualificationBlockerCode.POLICY_HASH_MISMATCH)
        if study.qualification_policy_version != policy.policy_version:
            blockers.append(StateModelQualificationBlockerCode.POLICY_BINDING_MISMATCH)
        if study.qualification_policy_hash.lower() != policy.content_hash.lower():
            blockers.append(StateModelQualificationBlockerCode.POLICY_BINDING_MISMATCH)
        if not policy.activated_at <= study.evaluated_at < policy.valid_until:
            blockers.append(StateModelQualificationBlockerCode.POLICY_INACTIVE)
        if not policy.activated_at <= assessed_at < policy.valid_until:
            blockers.append(StateModelQualificationBlockerCode.POLICY_INACTIVE)
        evidence_by_key = {item.metric_key: item for item in study.metrics}
        criteria_by_key = {item.metric_key: item for item in policy.metric_criteria}
        if (
            set(evidence_by_key) != set(criteria_by_key)
            or frozenset(criteria_by_key) != REQUIRED_QUALIFICATION_METRIC_KEYS
        ):
            blockers.append(StateModelQualificationBlockerCode.METRIC_SET_MISMATCH)
        results: list[ComparativeMetricResult] = []
        baseline_by_key = (
            {item.metric_key: item for item in baseline_shortfall.metrics}
            if baseline_shortfall is not None
            else {}
        )
        candidate_metrics = _candidate_metric_values(candidate) if candidate is not None else {}
        derived_metrics = (
            derived_metric_bundle.metric_values
            if isinstance(derived_metric_bundle, StateModelDerivedMetricBundle)
            else {}
        )
        for criterion in policy.metric_criteria:
            evidence = evidence_by_key.get(criterion.metric_key)
            if evidence is None:
                continue
            if evidence.unit != criterion.unit:
                blockers.append(StateModelQualificationBlockerCode.METRIC_UNIT_MISMATCH)
            baseline_metric = baseline_by_key.get(criterion.metric_key)
            if (
                baseline_metric is None
                or baseline_metric.unit != evidence.unit
                or baseline_metric.value != evidence.baseline_value
            ):
                blockers.append(StateModelQualificationBlockerCode.BASELINE_METRIC_BINDING_MISMATCH)
            authoritative_candidate_value = candidate_metrics.get(criterion.metric_key)
            if (
                authoritative_candidate_value is not None
                and authoritative_candidate_value != evidence.candidate_value
            ):
                blockers.append(
                    StateModelQualificationBlockerCode.CANDIDATE_METRIC_BINDING_MISMATCH
                )
            authoritative_derived_value = derived_metrics.get(criterion.metric_key)
            if (
                authoritative_derived_value is not None
                and authoritative_derived_value != evidence.candidate_value
            ):
                blockers.append(StateModelQualificationBlockerCode.DERIVED_METRIC_VALUE_MISMATCH)
            delta = criterion.improvement_delta(
                baseline=evidence.baseline_value,
                candidate=evidence.candidate_value,
            )
            passed = delta >= criterion.minimum_improvement_delta
            if not passed:
                blockers.append(StateModelQualificationBlockerCode.METRIC_MINIMUM_DELTA_NOT_MET)
            results.append(
                ComparativeMetricResult(
                    metric_key=criterion.metric_key,
                    unit=criterion.unit,
                    direction=criterion.direction,
                    baseline_value=evidence.baseline_value,
                    candidate_value=evidence.candidate_value,
                    improvement_delta=delta,
                    minimum_improvement_delta=criterion.minimum_improvement_delta,
                    passed=passed,
                )
            )
        metric_results = tuple(results)

        criteria_by_coefficient = {
            item.coefficient_key: item for item in policy.coefficient_criteria
        }
        evidence_by_coefficient = {item.coefficient_key: item for item in study.policy_coefficients}
        expected_contract = {
            (item.coefficient_key, item.target_code, item.lag_periods)
            for item in policy.coefficient_criteria
        }
        actual_contract = {
            (item.coefficient_key, item.target_code, item.lag_periods)
            for item in study.policy_coefficients
        }
        candidate_targets = (
            {
                (target.target_code, candidate.policy_reaction.reaction_lag_periods)
                for target in candidate.policy_reaction.targets
            }
            if candidate is not None and candidate.policy_reaction is not None
            else set()
        )
        if (
            expected_contract != actual_contract
            or {
                (criterion.target_code, criterion.lag_periods)
                for criterion in policy.coefficient_criteria
            }
            != candidate_targets
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_TARGET_SET_MISMATCH)
        for coefficient_key, coefficient_criterion in criteria_by_coefficient.items():
            coefficient_evidence = evidence_by_coefficient.get(coefficient_key)
            if coefficient_evidence is None:
                continue
            sign_matches = (
                coefficient_evidence.estimate > 0
                if coefficient_criterion.expected_sign is PolicyCoefficientSign.POSITIVE
                else coefficient_evidence.estimate < 0
            )
            interval_matches = (
                coefficient_evidence.confidence_interval_lower > 0
                if coefficient_criterion.expected_sign is PolicyCoefficientSign.POSITIVE
                else coefficient_evidence.confidence_interval_upper < 0
            )
            if not sign_matches:
                blockers.append(StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGN_MISMATCH)
            if not interval_matches:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_INTERVAL_FAILED
                )
            if coefficient_evidence.p_value > coefficient_criterion.maximum_p_value:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_SIGNIFICANCE_FAILED
                )
            if abs(coefficient_evidence.estimate) < coefficient_criterion.minimum_absolute_estimate:
                blockers.append(
                    StateModelQualificationBlockerCode.POLICY_COEFFICIENT_MAGNITUDE_FAILED
                )

        diagnostics = study.policy_diagnostics
        if diagnostics.sample_count != study.sample_count:
            blockers.append(StateModelQualificationBlockerCode.SAMPLE_COUNT_MISMATCH)
        if diagnostics.sample_count < policy.minimum_policy_sample_count:
            blockers.append(StateModelQualificationBlockerCode.POLICY_SAMPLE_INSUFFICIENT)
        if diagnostics.adjusted_r_squared < policy.minimum_adjusted_r_squared:
            blockers.append(StateModelQualificationBlockerCode.POLICY_ADJUSTED_R_SQUARED_FAILED)
        if (
            diagnostics.residual_autocorrelation_p_value
            < policy.minimum_residual_autocorrelation_p_value
        ):
            blockers.append(StateModelQualificationBlockerCode.POLICY_RESIDUAL_DIAGNOSTIC_FAILED)
        if diagnostics.heteroskedasticity_p_value < policy.minimum_heteroskedasticity_p_value:
            blockers.append(
                StateModelQualificationBlockerCode.POLICY_HETEROSKEDASTICITY_DIAGNOSTIC_FAILED
            )
        if diagnostics.parameter_stability_p_value < policy.minimum_parameter_stability_p_value:
            blockers.append(StateModelQualificationBlockerCode.POLICY_PARAMETER_STABILITY_FAILED)
        if diagnostics.condition_number > policy.maximum_condition_number:
            blockers.append(StateModelQualificationBlockerCode.POLICY_CONDITION_NUMBER_FAILED)

    if candidate is not None and baseline_shortfall is not None:
        expected_window = (
            candidate.oos_metrics.window_start,
            candidate.oos_metrics.window_end,
            baseline_shortfall.window_start,
            baseline_shortfall.window_end,
            study.oos_window_start,
            study.oos_window_end,
        )
        if len(set(expected_window[::2])) != 1 or len(set(expected_window[1::2])) != 1:
            blockers.append(StateModelQualificationBlockerCode.OOS_WINDOW_MISMATCH)
        if (
            candidate.oos_metrics.sample_count != baseline_shortfall.observation_count
            or study.sample_count != candidate.oos_metrics.sample_count
        ):
            blockers.append(StateModelQualificationBlockerCode.SAMPLE_COUNT_MISMATCH)

    return _build_assessment(
        study_id=study.study_id,
        assessed_at=assessed_at,
        study=study,
        preregistration=preregistration,
        baseline_shortfall=baseline_shortfall,
        candidate=candidate,
        advanced_assessment=(
            advanced_assessment
            if isinstance(advanced_assessment, AdvancedStateModelAssessmentAttestation)
            else None
        ),
        derived_metric_bundle=(
            derived_metric_bundle
            if isinstance(derived_metric_bundle, StateModelDerivedMetricBundle)
            else None
        ),
        policy=policy,
        metric_results=metric_results,
        blockers=blockers,
    )


__all__ = [
    "AdvancedStateModelAssessmentAttestation",
    "ComparativeMetricCriterion",
    "ComparativeMetricEvidence",
    "ComparativeMetricResult",
    "MetricImprovementDirection",
    "PolicyCoefficientCriterion",
    "PolicyCoefficientSign",
    "PolicyReactionCoefficientEvidence",
    "PolicyReactionDiagnosticEvidence",
    "StateModelComparativeStudyEvidence",
    "StateModelDerivedMetricBundle",
    "StateModelQualificationAssessment",
    "StateModelQualificationBlockerCode",
    "StateModelQualificationPolicy",
    "StateModelQualificationStatus",
    "StateModelStudyPreregistration",
    "advanced_state_threshold_hash",
    "attest_advanced_state_model_assessment",
    "evaluate_state_model_qualification",
    "missing_state_model_qualification_assessment",
]
