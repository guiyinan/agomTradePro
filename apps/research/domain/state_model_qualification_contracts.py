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
    StateModelPITManifestEvidence,
    evaluate_advanced_state_model_evidence,
)
from apps.research.domain.state_model_baseline import (
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
    "StateModelQualificationBlockerCode",
    "StateModelQualificationPolicy",
    "StateModelQualificationStatus",
    "StateModelStudyPreregistration",
    "advanced_state_threshold_hash",
    "attest_advanced_state_model_assessment",
]
