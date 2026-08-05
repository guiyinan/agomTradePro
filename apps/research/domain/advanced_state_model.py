"""Fail-closed R6 contracts for externally precomputed advanced state models.

The module validates research evidence only.  It deliberately contains no
Markov, HMM, Bayesian, or policy-reaction training implementation and cannot
publish current state, authorize decisions, or replace the canonical Regime.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from apps.research.domain.state_model_baseline import (
    BaselineShortfallDecision,
    BaselineShortfallReport,
)


def _require_text(value: str, field_name: str, *, maximum: int = 500) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


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


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class AdvancedStateMethodology(str, Enum):
    """Pre-registered R6 candidate methodology."""

    MARKOV_SWITCHING = "markov_switching"
    HIDDEN_MARKOV_MODEL = "hidden_markov_model"
    DYNAMIC_BAYESIAN = "dynamic_bayesian"
    POLICY_REACTION = "policy_reaction"


class StateModelLifecycleStatus(str, Enum):
    """Research lifecycle before any future promotion flow."""

    RESEARCH_ONLY = "research_only"
    RETIRED = "retired"


class InvalidationDirection(str, Enum):
    """Direction in which a monitored metric invalidates a candidate."""

    ABOVE_MAXIMUM = "above_maximum"
    BELOW_MINIMUM = "below_minimum"


class AdvancedStateModelAssessmentStatus(str, Enum):
    """Outcome of the external-evidence acceptance gate."""

    ACCEPTED = "accepted"
    BLOCKED = "blocked"


class AdvancedStateModelBlockerCode(str, Enum):
    """Stable reasons why R6 evidence remains research-blocked."""

    CANDIDATE_EVIDENCE_MISSING = "advanced_state_model.candidate.missing"
    CANDIDATE_HASH_MISMATCH = "advanced_state_model.candidate.hash_mismatch"
    CANDIDATE_EVIDENCE_STALE = "advanced_state_model.candidate.stale"
    CANDIDATE_RETIRED = "advanced_state_model.candidate.retired"
    EXTERNAL_EVIDENCE_FROM_FUTURE = "advanced_state_model.evidence.from_future"
    BASELINE_SHORTFALL_MISSING = "advanced_state_model.baseline_shortfall.missing"
    BASELINE_SHORTFALL_NOT_PROVEN = "advanced_state_model.baseline_shortfall.not_proven"
    BASELINE_BINDING_MISMATCH = "advanced_state_model.baseline_shortfall.binding_mismatch"
    BASELINE_COMPARISON_NOT_IMPROVED = "advanced_state_model.baseline.not_improved"
    PIT_MANIFEST_MISSING = "advanced_state_model.pit.missing"
    PIT_MANIFEST_UNVERIFIED = "advanced_state_model.pit.unverified"
    PIT_MANIFEST_INCOMPLETE = "advanced_state_model.pit.incomplete"
    PIT_MANIFEST_MISMATCH = "advanced_state_model.pit.identity_mismatch"
    PIT_MANIFEST_FROM_FUTURE = "advanced_state_model.pit.from_future"
    PIT_MANIFEST_STALE = "advanced_state_model.pit.stale"
    PIT_INPUT_VERSION_HASH_MISMATCH = "advanced_state_model.pit.input_mismatch"
    ARTIFACT_ATTESTATION_MISSING = "advanced_state_model.artifact.attestation_missing"
    ARTIFACT_ATTESTATION_UNVERIFIED = "advanced_state_model.artifact.unverified"
    ARTIFACT_HASH_MISMATCH = "advanced_state_model.artifact.hash_mismatch"
    ARTIFACT_ATTESTATION_FROM_FUTURE = "advanced_state_model.artifact.from_future"
    ARTIFACT_ATTESTATION_STALE = "advanced_state_model.artifact.stale"
    LABEL_PROTOCOL_UNSTABLE = "advanced_state_model.labels.unstable"
    LABEL_DRIFT_DETECTED = "advanced_state_model.labels.drift_detected"
    LABEL_SET_MISMATCH = "advanced_state_model.labels.set_mismatch"
    STATE_PROBABILITY_SUM_INVALID = "advanced_state_model.probability.sum_invalid"
    TRANSITION_ROW_SUM_INVALID = "advanced_state_model.transition.sum_invalid"
    DURATION_EVIDENCE_INSUFFICIENT = "advanced_state_model.duration.insufficient"
    OOS_TRANSITION_ACCURACY_BELOW_MINIMUM = (
        "advanced_state_model.oos.transition_accuracy_below_minimum"
    )
    OOS_LOG_LOSS_ABOVE_MAXIMUM = "advanced_state_model.oos.log_loss_above_maximum"
    OOS_CALIBRATION_ABOVE_MAXIMUM = "advanced_state_model.oos.calibration_above_maximum"
    POLICY_TARGET_CONTRACT_MISSING = "advanced_state_model.policy_target.missing"
    POLICY_TARGET_INPUT_MISMATCH = "advanced_state_model.policy_target.input_mismatch"
    ACCEPTANCE_THRESHOLDS_MISSING = "advanced_state_model.thresholds.missing"
    ACCEPTANCE_THRESHOLD_VERSION_MISMATCH = "advanced_state_model.thresholds.version_mismatch"
    ACCEPTANCE_THRESHOLDS_INACTIVE = "advanced_state_model.thresholds.inactive"
    GOVERNANCE_POLICY_INACTIVE = "advanced_state_model.governance.inactive"


@dataclass(frozen=True)
class StateModelInputReference:
    """One exact input version/hash selected by the PIT manifest."""

    input_key: str
    dataset_key: str
    input_version: str
    content_hash: str
    pit_version_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in ("input_key", "dataset_key", "input_version"):
            _require_token(str(getattr(self, name)), f"StateModelInputReference.{name}")
        _require_sha256(self.content_hash, "StateModelInputReference.content_hash")
        if not self.pit_version_ids:
            raise ValueError("StateModelInputReference.pit_version_ids cannot be empty")
        for version_id in self.pit_version_ids:
            _require_positive_int(version_id, "StateModelInputReference.pit_version_id")
        if len(self.pit_version_ids) != len(set(self.pit_version_ids)):
            raise ValueError("StateModelInputReference.pit_version_ids must be unique")


@dataclass(frozen=True)
class StateModelPITManifestEvidence:
    """Canonical Data Center PIT evidence projected through Application."""

    manifest_id: str
    manifest_hash: str
    as_of_time: datetime
    valid_until: datetime
    is_verified: bool
    is_complete: bool
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    inputs: tuple[StateModelInputReference, ...]

    def __post_init__(self) -> None:
        _require_token(self.manifest_id, "StateModelPITManifestEvidence.manifest_id")
        _require_sha256(self.manifest_hash, "StateModelPITManifestEvidence.manifest_hash")
        _require_aware(self.as_of_time, "StateModelPITManifestEvidence.as_of_time")
        _require_aware(self.valid_until, "StateModelPITManifestEvidence.valid_until")
        if self.valid_until <= self.as_of_time:
            raise ValueError("PIT manifest valid_until must follow as_of_time")
        if not isinstance(self.is_verified, bool) or not isinstance(self.is_complete, bool):
            raise ValueError("PIT manifest verification fields must be booleans")
        _require_finite(self.coverage_ratio, "StateModelPITManifestEvidence.coverage_ratio")
        if not Decimal("0") <= self.coverage_ratio <= Decimal("1"):
            raise ValueError("PIT manifest coverage_ratio must be between zero and one")
        for name in ("missing_count", "estimated_count", "unknown_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"StateModelPITManifestEvidence.{name} cannot be negative")
        identities = tuple(item.input_key for item in self.inputs)
        if not identities or len(identities) != len(set(identities)):
            raise ValueError("PIT manifest inputs must be non-empty and uniquely keyed")

    @property
    def complete_verified_scope(self) -> bool:
        """Return whether all required PIT inputs are verified and complete."""

        return (
            self.is_verified
            and self.is_complete
            and self.coverage_ratio == Decimal("1")
            and self.missing_count == 0
            and self.estimated_count == 0
            and self.unknown_count == 0
        )


@dataclass(frozen=True)
class EconomicStateLabel:
    """Stable, economically named state independent of numeric label order."""

    state_id: str
    economic_name: str
    economic_definition: str

    def __post_init__(self) -> None:
        _require_token(self.state_id, "EconomicStateLabel.state_id")
        _require_text(self.economic_name, "EconomicStateLabel.economic_name", maximum=160)
        _require_text(
            self.economic_definition,
            "EconomicStateLabel.economic_definition",
            maximum=1_000,
        )


@dataclass(frozen=True)
class StateLabelProtocol:
    """Versioned label-alignment and stability evidence."""

    protocol_version: str
    alignment_method: str
    labels: tuple[EconomicStateLabel, ...]
    stability_evidence_ref: str
    stability_evidence_hash: str
    verified_at: datetime
    is_stable: bool
    drift_detected: bool

    def __post_init__(self) -> None:
        _require_token(self.protocol_version, "StateLabelProtocol.protocol_version")
        _require_token(self.alignment_method, "StateLabelProtocol.alignment_method")
        _require_text(
            self.stability_evidence_ref,
            "StateLabelProtocol.stability_evidence_ref",
        )
        _require_sha256(
            self.stability_evidence_hash,
            "StateLabelProtocol.stability_evidence_hash",
        )
        _require_aware(self.verified_at, "StateLabelProtocol.verified_at")
        if not isinstance(self.is_stable, bool) or not isinstance(self.drift_detected, bool):
            raise ValueError("state-label stability fields must be booleans")
        if len(self.labels) < 2:
            raise ValueError("state-label protocol requires at least two economic states")
        state_ids = tuple(label.state_id for label in self.labels)
        economic_names = tuple(label.economic_name.casefold() for label in self.labels)
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("state-label identities must be unique")
        if len(economic_names) != len(set(economic_names)):
            raise ValueError("economic state names must be unique")

    @property
    def state_ids(self) -> frozenset[str]:
        """Return immutable state identities used by all evidence matrices."""

        return frozenset(label.state_id for label in self.labels)


@dataclass(frozen=True)
class StateProbability:
    """One finite probability assigned to an economic state."""

    state_id: str
    probability: Decimal

    def __post_init__(self) -> None:
        _require_token(self.state_id, "StateProbability.state_id")
        _require_finite(self.probability, "StateProbability.probability")
        if not Decimal("0") <= self.probability <= Decimal("1"):
            raise ValueError("state probability must be between zero and one")


@dataclass(frozen=True)
class StateProbabilityDistribution:
    """Externally calculated probability distribution at one observation time."""

    observed_at: datetime
    probabilities: tuple[StateProbability, ...]

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "StateProbabilityDistribution.observed_at")
        state_ids = tuple(item.state_id for item in self.probabilities)
        if not state_ids or len(state_ids) != len(set(state_ids)):
            raise ValueError("state distribution must be non-empty and uniquely keyed")


@dataclass(frozen=True)
class StateTransitionRow:
    """One externally calculated transition-probability row."""

    from_state_id: str
    probabilities: tuple[StateProbability, ...]

    def __post_init__(self) -> None:
        _require_token(self.from_state_id, "StateTransitionRow.from_state_id")
        destinations = tuple(item.state_id for item in self.probabilities)
        if not destinations or len(destinations) != len(set(destinations)):
            raise ValueError("transition destinations must be non-empty and unique")


@dataclass(frozen=True)
class StateTransitionMatrixEvidence:
    """Versioned transition matrix produced by the external artifact."""

    matrix_version: str
    observed_at: datetime
    horizon_periods: int
    rows: tuple[StateTransitionRow, ...]

    def __post_init__(self) -> None:
        _require_token(self.matrix_version, "StateTransitionMatrixEvidence.matrix_version")
        _require_aware(self.observed_at, "StateTransitionMatrixEvidence.observed_at")
        _require_positive_int(
            self.horizon_periods,
            "StateTransitionMatrixEvidence.horizon_periods",
        )
        origins = tuple(row.from_state_id for row in self.rows)
        if not origins or len(origins) != len(set(origins)):
            raise ValueError("transition rows must be non-empty and uniquely keyed")


@dataclass(frozen=True)
class StateDurationEvidence:
    """Expected and observed duration evidence for one named state."""

    state_id: str
    mean_duration_periods: Decimal
    median_duration_periods: Decimal
    observation_count: int

    def __post_init__(self) -> None:
        _require_token(self.state_id, "StateDurationEvidence.state_id")
        _require_finite(self.mean_duration_periods, "mean_duration_periods")
        _require_finite(self.median_duration_periods, "median_duration_periods")
        if self.mean_duration_periods <= 0 or self.median_duration_periods <= 0:
            raise ValueError("state duration estimates must be positive")
        _require_positive_int(self.observation_count, "StateDurationEvidence.observation_count")


@dataclass(frozen=True)
class StateModelOOSMetrics:
    """Required OOS transition, log-loss, calibration, and duration metrics."""

    window_start: datetime
    window_end: datetime
    sample_count: int
    transition_accuracy: Decimal
    log_loss: Decimal
    calibration_error: Decimal
    duration_mae_periods: Decimal
    evaluated_at: datetime
    evidence_ref: str
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in ("window_start", "window_end", "evaluated_at"):
            _require_aware(getattr(self, name), f"StateModelOOSMetrics.{name}")
        if self.window_end <= self.window_start:
            raise ValueError("OOS window_end must follow window_start")
        if self.evaluated_at < self.window_end:
            raise ValueError("OOS evaluation cannot predate its sample window")
        _require_positive_int(self.sample_count, "StateModelOOSMetrics.sample_count")
        for name in (
            "transition_accuracy",
            "log_loss",
            "calibration_error",
            "duration_mae_periods",
        ):
            _require_finite(getattr(self, name), f"StateModelOOSMetrics.{name}")
        if not Decimal("0") <= self.transition_accuracy <= Decimal("1"):
            raise ValueError("transition_accuracy must be between zero and one")
        if self.log_loss < 0 or self.calibration_error < 0 or self.duration_mae_periods < 0:
            raise ValueError("OOS loss, calibration, and duration error cannot be negative")
        _require_text(self.evidence_ref, "StateModelOOSMetrics.evidence_ref")
        _require_sha256(self.evidence_hash, "StateModelOOSMetrics.evidence_hash")


@dataclass(frozen=True)
class SimpleBaselineComparisonEvidence:
    """Advanced-model comparison bound to one baseline-shortfall report."""

    baseline_key: str
    baseline_version: str
    shortfall_specification_version: str
    shortfall_evaluation_id: str
    shortfall_report_hash: str
    compared_at: datetime
    evidence_ref: str
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in (
            "baseline_key",
            "baseline_version",
            "shortfall_specification_version",
            "shortfall_evaluation_id",
        ):
            _require_token(str(getattr(self, name)), f"SimpleBaselineComparison.{name}")
        _require_sha256(
            self.shortfall_report_hash,
            "SimpleBaselineComparison.shortfall_report_hash",
        )
        _require_aware(self.compared_at, "SimpleBaselineComparison.compared_at")
        _require_text(self.evidence_ref, "SimpleBaselineComparison.evidence_ref")
        _require_sha256(self.evidence_hash, "SimpleBaselineComparison.evidence_hash")


@dataclass(frozen=True)
class PolicyTargetDefinition:
    """Versioned policy target consumed by a reaction specification."""

    target_code: str
    dataset_key: str
    input_version: str
    unit: str
    economic_role: str

    def __post_init__(self) -> None:
        for name in ("target_code", "dataset_key", "input_version", "unit", "economic_role"):
            _require_token(str(getattr(self, name)), f"PolicyTargetDefinition.{name}")


@dataclass(frozen=True)
class PolicyReactionSpecification:
    """Complete, versioned policy target and reaction contract."""

    specification_version: str
    policy_instrument_code: str
    reaction_equation_version: str
    reaction_lag_periods: int
    targets: tuple[PolicyTargetDefinition, ...]
    evidence_ref: str
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in (
            "specification_version",
            "policy_instrument_code",
            "reaction_equation_version",
        ):
            _require_token(str(getattr(self, name)), f"PolicyReactionSpecification.{name}")
        _require_positive_int(
            self.reaction_lag_periods,
            "PolicyReactionSpecification.reaction_lag_periods",
        )
        target_codes = tuple(target.target_code for target in self.targets)
        if not target_codes or len(target_codes) != len(set(target_codes)):
            raise ValueError("policy targets must be non-empty and uniquely keyed")
        _require_text(self.evidence_ref, "PolicyReactionSpecification.evidence_ref")
        _require_sha256(self.evidence_hash, "PolicyReactionSpecification.evidence_hash")


@dataclass(frozen=True)
class ExternalStateModelArtifact:
    """Version/hash metadata for an externally precomputed model artifact."""

    artifact_id: str
    methodology: AdvancedStateMethodology
    producer_ref: str
    produced_at: datetime
    code_version: str
    parameter_version: str
    parameter_hash: str
    artifact_hash: str
    computation_origin: str

    def __post_init__(self) -> None:
        _require_token(self.artifact_id, "ExternalStateModelArtifact.artifact_id")
        if not isinstance(self.methodology, AdvancedStateMethodology):
            raise ValueError("external artifact methodology is invalid")
        _require_text(self.producer_ref, "ExternalStateModelArtifact.producer_ref")
        _require_aware(self.produced_at, "ExternalStateModelArtifact.produced_at")
        _require_token(self.code_version, "ExternalStateModelArtifact.code_version")
        _require_token(self.parameter_version, "ExternalStateModelArtifact.parameter_version")
        _require_sha256(self.parameter_hash, "ExternalStateModelArtifact.parameter_hash")
        _require_sha256(self.artifact_hash, "ExternalStateModelArtifact.artifact_hash")
        if self.computation_origin != "external_precomputed":
            raise ValueError("state-model artifact must be external_precomputed")


@dataclass(frozen=True)
class ExternalArtifactAttestation:
    """Owner attestation independently verifying the external artifact hash."""

    artifact_id: str
    methodology: AdvancedStateMethodology
    artifact_hash: str
    verified: bool
    observed_at: datetime
    valid_until: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_token(self.artifact_id, "ExternalArtifactAttestation.artifact_id")
        if not isinstance(self.methodology, AdvancedStateMethodology):
            raise ValueError("artifact attestation methodology is invalid")
        _require_sha256(self.artifact_hash, "ExternalArtifactAttestation.artifact_hash")
        if not isinstance(self.verified, bool):
            raise ValueError("artifact attestation verified must be a boolean")
        _require_aware(self.observed_at, "ExternalArtifactAttestation.observed_at")
        _require_aware(self.valid_until, "ExternalArtifactAttestation.valid_until")
        if self.valid_until <= self.observed_at:
            raise ValueError("artifact attestation valid_until must follow observed_at")
        _require_text(self.evidence_ref, "ExternalArtifactAttestation.evidence_ref")


@dataclass(frozen=True)
class StateModelInvalidationRule:
    """Versioned monitoring threshold that can invalidate research evidence."""

    rule_id: str
    metric_name: str
    direction: InvalidationDirection
    threshold: Decimal
    consecutive_windows: int

    def __post_init__(self) -> None:
        _require_token(self.rule_id, "StateModelInvalidationRule.rule_id")
        _require_token(self.metric_name, "StateModelInvalidationRule.metric_name")
        if not isinstance(self.direction, InvalidationDirection):
            raise ValueError("state-model invalidation direction is invalid")
        _require_finite(self.threshold, "StateModelInvalidationRule.threshold")
        _require_positive_int(
            self.consecutive_windows,
            "StateModelInvalidationRule.consecutive_windows",
        )


@dataclass(frozen=True)
class AdvancedStateModelGovernancePolicy:
    """Versioned expiry, invalidation, and retirement policy."""

    policy_version: str
    activated_at: datetime
    valid_until: datetime
    invalidation_rules: tuple[StateModelInvalidationRule, ...]
    retirement_owner: str
    retirement_protocol_version: str

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "AdvancedStateModelGovernancePolicy.policy_version")
        _require_aware(self.activated_at, "AdvancedStateModelGovernancePolicy.activated_at")
        _require_aware(self.valid_until, "AdvancedStateModelGovernancePolicy.valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("state-model governance valid_until must follow activated_at")
        rule_ids = tuple(rule.rule_id for rule in self.invalidation_rules)
        if not rule_ids or len(rule_ids) != len(set(rule_ids)):
            raise ValueError("governance invalidation rules must be non-empty and unique")
        _require_token(self.retirement_owner, "AdvancedStateModelGovernancePolicy.retirement_owner")
        _require_token(
            self.retirement_protocol_version,
            "AdvancedStateModelGovernancePolicy.retirement_protocol_version",
        )


@dataclass(frozen=True)
class StateModelRetirementEvidence:
    """Append-only retirement evidence for an invalidated research candidate."""

    event_id: str
    retired_at: datetime
    reason_codes: tuple[str, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_token(self.event_id, "StateModelRetirementEvidence.event_id")
        _require_aware(self.retired_at, "StateModelRetirementEvidence.retired_at")
        if not self.reason_codes:
            raise ValueError("state-model retirement reasons cannot be empty")
        for reason in self.reason_codes:
            _require_token(reason, "StateModelRetirementEvidence.reason_code")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("state-model retirement reasons must be unique")
        _require_sha256(self.evidence_hash, "StateModelRetirementEvidence.evidence_hash")


@dataclass(frozen=True)
class AdvancedStateModelAcceptanceThresholds:
    """Injected acceptance gates; no model threshold is hardcoded."""

    threshold_version: str
    minimum_transition_accuracy: Decimal
    maximum_log_loss: Decimal
    maximum_calibration_error: Decimal
    probability_sum_tolerance: Decimal
    minimum_duration_observations: int
    activated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _require_token(self.threshold_version, "AcceptanceThresholds.threshold_version")
        for name in (
            "minimum_transition_accuracy",
            "maximum_log_loss",
            "maximum_calibration_error",
            "probability_sum_tolerance",
        ):
            _require_finite(getattr(self, name), f"AcceptanceThresholds.{name}")
        if not Decimal("0") <= self.minimum_transition_accuracy <= Decimal("1"):
            raise ValueError("minimum_transition_accuracy must be between zero and one")
        if self.maximum_log_loss < 0 or self.maximum_calibration_error < 0:
            raise ValueError("maximum OOS losses cannot be negative")
        if not Decimal("0") <= self.probability_sum_tolerance < Decimal("1"):
            raise ValueError("probability_sum_tolerance must be in [0, 1)")
        _require_positive_int(
            self.minimum_duration_observations,
            "AcceptanceThresholds.minimum_duration_observations",
        )
        _require_aware(self.activated_at, "AcceptanceThresholds.activated_at")
        _require_aware(self.valid_until, "AcceptanceThresholds.valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("acceptance threshold valid_until must follow activated_at")


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
    return value


@dataclass(frozen=True)
class AdvancedStateModelCandidateEvidence:
    """Complete external R6 evidence; never a Regime replacement."""

    candidate_id: str
    candidate_version: str
    methodology: AdvancedStateMethodology
    hypothesis: str
    baseline_comparison: SimpleBaselineComparisonEvidence
    pit_manifest_id: str
    pit_manifest_hash: str
    input_references: tuple[StateModelInputReference, ...]
    label_protocol: StateLabelProtocol
    state_distribution: StateProbabilityDistribution
    transition_matrix: StateTransitionMatrixEvidence
    duration_evidence: tuple[StateDurationEvidence, ...]
    oos_metrics: StateModelOOSMetrics
    policy_reaction: PolicyReactionSpecification | None
    artifact: ExternalStateModelArtifact
    acceptance_threshold_version: str
    governance_policy: AdvancedStateModelGovernancePolicy
    lifecycle_status: StateModelLifecycleStatus
    retirement_evidence: StateModelRetirementEvidence | None
    valid_until: datetime
    evidence_hash: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool

    def __post_init__(self) -> None:
        _require_token(self.candidate_id, "AdvancedStateModelCandidate.candidate_id")
        _require_token(self.candidate_version, "AdvancedStateModelCandidate.candidate_version")
        if not isinstance(self.methodology, AdvancedStateMethodology):
            raise ValueError("advanced state-model methodology is invalid")
        _require_text(self.hypothesis, "AdvancedStateModelCandidate.hypothesis", maximum=1_000)
        _require_token(self.pit_manifest_id, "AdvancedStateModelCandidate.pit_manifest_id")
        _require_sha256(self.pit_manifest_hash, "AdvancedStateModelCandidate.pit_manifest_hash")
        input_keys = tuple(item.input_key for item in self.input_references)
        if not input_keys or len(input_keys) != len(set(input_keys)):
            raise ValueError("candidate input references must be non-empty and unique")
        if self.artifact.methodology is not self.methodology:
            raise ValueError("candidate and external artifact methodology must match")
        _require_token(
            self.acceptance_threshold_version,
            "AdvancedStateModelCandidate.acceptance_threshold_version",
        )
        if not isinstance(self.lifecycle_status, StateModelLifecycleStatus):
            raise ValueError("advanced state-model lifecycle status is invalid")
        if self.lifecycle_status is StateModelLifecycleStatus.RETIRED:
            if self.retirement_evidence is None:
                raise ValueError("retired state-model candidate requires retirement evidence")
        elif self.retirement_evidence is not None:
            raise ValueError("research-only candidate cannot carry retirement evidence")
        _require_aware(self.valid_until, "AdvancedStateModelCandidate.valid_until")
        if self.valid_until <= self.artifact.produced_at:
            raise ValueError("candidate valid_until must follow artifact production")
        _require_sha256(self.evidence_hash, "AdvancedStateModelCandidate.evidence_hash")
        if (
            self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_replace_regime is not True
        ):
            raise ValueError("advanced state-model evidence must remain research-only")

    def canonical_payload(self) -> dict[str, object]:
        """Return all evidence except its declared sealing hash canonically."""

        return {
            field.name: _canonical_value(getattr(self, field.name))
            for field in fields(self)
            if field.name != "evidence_hash"
        }

    @property
    def calculated_evidence_hash(self) -> str:
        """Return the digest sealing candidate inputs, outputs, and governance."""

        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AdvancedStateModelAssessment:
    """Fail-closed assessment that never changes canonical Regime state."""

    status: AdvancedStateModelAssessmentStatus
    candidate_id: str
    candidate_version: str | None
    methodology: AdvancedStateMethodology | None
    artifact_hash: str | None
    pit_manifest_id: str | None
    pit_manifest_hash: str | None
    label_protocol_version: str | None
    assessed_at: datetime
    blockers: tuple[AdvancedStateModelBlockerCode, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdvancedStateModelAssessmentStatus):
            raise ValueError("advanced state-model assessment status is invalid")
        _require_token(self.candidate_id, "AdvancedStateModelAssessment.candidate_id")
        _require_aware(self.assessed_at, "AdvancedStateModelAssessment.assessed_at")
        if self.status is AdvancedStateModelAssessmentStatus.ACCEPTED:
            required = (
                self.candidate_version,
                self.methodology,
                self.artifact_hash,
                self.pit_manifest_id,
                self.pit_manifest_hash,
                self.label_protocol_version,
            )
            if any(value is None for value in required) or self.blockers:
                raise ValueError("accepted state-model assessment requires complete references")
        elif not self.blockers:
            raise ValueError("blocked state-model assessment requires stable blockers")
        if (
            self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_replace_regime is not True
        ):
            raise ValueError("state-model assessment cannot authorize Regime replacement")


def _input_signature(
    inputs: tuple[StateModelInputReference, ...],
) -> dict[str, tuple[str, str, str, tuple[int, ...]]]:
    return {
        item.input_key: (
            item.dataset_key,
            item.input_version,
            item.content_hash.lower(),
            item.pit_version_ids,
        )
        for item in inputs
    }


def _sum_is_one(probabilities: tuple[StateProbability, ...], tolerance: Decimal) -> bool:
    total = sum((item.probability for item in probabilities), Decimal("0"))
    return abs(total - Decimal("1")) <= tolerance


def _assessment(
    candidate: AdvancedStateModelCandidateEvidence,
    *,
    evaluated_at: datetime,
    blockers: list[AdvancedStateModelBlockerCode],
) -> AdvancedStateModelAssessment:
    unique_blockers = tuple(dict.fromkeys(blockers))
    return AdvancedStateModelAssessment(
        status=(
            AdvancedStateModelAssessmentStatus.BLOCKED
            if unique_blockers
            else AdvancedStateModelAssessmentStatus.ACCEPTED
        ),
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        methodology=candidate.methodology,
        artifact_hash=candidate.artifact.artifact_hash,
        pit_manifest_id=candidate.pit_manifest_id,
        pit_manifest_hash=candidate.pit_manifest_hash,
        label_protocol_version=candidate.label_protocol.protocol_version,
        assessed_at=evaluated_at,
        blockers=unique_blockers,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )


def evaluate_advanced_state_model_evidence(
    *,
    candidate: AdvancedStateModelCandidateEvidence,
    baseline_shortfall: BaselineShortfallReport | None,
    pit_manifest: StateModelPITManifestEvidence | None,
    artifact_attestation: ExternalArtifactAttestation | None,
    thresholds: AdvancedStateModelAcceptanceThresholds,
    evaluated_at: datetime,
) -> AdvancedStateModelAssessment:
    """Accept R6 evidence only when every independent gate passes."""

    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[AdvancedStateModelBlockerCode] = []
    comparison = candidate.baseline_comparison
    if baseline_shortfall is None:
        blockers.append(AdvancedStateModelBlockerCode.BASELINE_SHORTFALL_MISSING)
    else:
        if (
            baseline_shortfall.decision is not BaselineShortfallDecision.PROVEN
            or not baseline_shortfall.can_propose_advanced_model_research
        ):
            blockers.append(AdvancedStateModelBlockerCode.BASELINE_SHORTFALL_NOT_PROVEN)
        if (
            comparison.baseline_key != baseline_shortfall.baseline_key
            or comparison.baseline_version != baseline_shortfall.baseline_version
            or comparison.shortfall_specification_version
            != baseline_shortfall.specification_version
            or comparison.shortfall_evaluation_id != baseline_shortfall.evaluation_id
            or comparison.shortfall_report_hash.lower() != baseline_shortfall.content_hash.lower()
            or baseline_shortfall.content_hash.lower() != baseline_shortfall.calculated_content_hash
        ):
            blockers.append(AdvancedStateModelBlockerCode.BASELINE_BINDING_MISMATCH)

    if pit_manifest is None:
        blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_MISSING)
    else:
        if not pit_manifest.is_verified:
            blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_UNVERIFIED)
        if not pit_manifest.complete_verified_scope:
            blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_INCOMPLETE)
        if (
            candidate.pit_manifest_id != pit_manifest.manifest_id
            or candidate.pit_manifest_hash.lower() != pit_manifest.manifest_hash.lower()
        ):
            blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_MISMATCH)
        if pit_manifest.as_of_time > evaluated_at:
            blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_FROM_FUTURE)
        if pit_manifest.valid_until <= evaluated_at:
            blockers.append(AdvancedStateModelBlockerCode.PIT_MANIFEST_STALE)
        if _input_signature(candidate.input_references) != _input_signature(pit_manifest.inputs):
            blockers.append(AdvancedStateModelBlockerCode.PIT_INPUT_VERSION_HASH_MISMATCH)

    artifact = candidate.artifact
    if artifact_attestation is None:
        blockers.append(AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_MISSING)
    else:
        if not artifact_attestation.verified:
            blockers.append(AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_UNVERIFIED)
        if (
            artifact.artifact_id != artifact_attestation.artifact_id
            or artifact.methodology is not artifact_attestation.methodology
            or artifact.artifact_hash.lower() != artifact_attestation.artifact_hash.lower()
        ):
            blockers.append(AdvancedStateModelBlockerCode.ARTIFACT_HASH_MISMATCH)
        if artifact_attestation.observed_at > evaluated_at:
            blockers.append(AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_FROM_FUTURE)
        if artifact_attestation.valid_until <= evaluated_at:
            blockers.append(AdvancedStateModelBlockerCode.ARTIFACT_ATTESTATION_STALE)

    if candidate.evidence_hash.lower() != candidate.calculated_evidence_hash:
        blockers.append(AdvancedStateModelBlockerCode.CANDIDATE_HASH_MISMATCH)
    if candidate.valid_until <= evaluated_at:
        blockers.append(AdvancedStateModelBlockerCode.CANDIDATE_EVIDENCE_STALE)
    if candidate.lifecycle_status is StateModelLifecycleStatus.RETIRED:
        blockers.append(AdvancedStateModelBlockerCode.CANDIDATE_RETIRED)
    evidence_times = (
        artifact.produced_at,
        candidate.label_protocol.verified_at,
        candidate.state_distribution.observed_at,
        candidate.transition_matrix.observed_at,
        candidate.oos_metrics.evaluated_at,
        comparison.compared_at,
    )
    if any(value > evaluated_at for value in evidence_times):
        blockers.append(AdvancedStateModelBlockerCode.EXTERNAL_EVIDENCE_FROM_FUTURE)

    if not candidate.label_protocol.is_stable:
        blockers.append(AdvancedStateModelBlockerCode.LABEL_PROTOCOL_UNSTABLE)
    if candidate.label_protocol.drift_detected:
        blockers.append(AdvancedStateModelBlockerCode.LABEL_DRIFT_DETECTED)
    expected_states = candidate.label_protocol.state_ids
    distribution_states = frozenset(
        item.state_id for item in candidate.state_distribution.probabilities
    )
    transition_origins = frozenset(row.from_state_id for row in candidate.transition_matrix.rows)
    transition_destinations = {
        frozenset(item.state_id for item in row.probabilities)
        for row in candidate.transition_matrix.rows
    }
    duration_states = frozenset(item.state_id for item in candidate.duration_evidence)
    if (
        distribution_states != expected_states
        or transition_origins != expected_states
        or transition_destinations != {expected_states}
        or duration_states != expected_states
    ):
        blockers.append(AdvancedStateModelBlockerCode.LABEL_SET_MISMATCH)

    if not _sum_is_one(
        candidate.state_distribution.probabilities,
        thresholds.probability_sum_tolerance,
    ):
        blockers.append(AdvancedStateModelBlockerCode.STATE_PROBABILITY_SUM_INVALID)
    if any(
        not _sum_is_one(row.probabilities, thresholds.probability_sum_tolerance)
        for row in candidate.transition_matrix.rows
    ):
        blockers.append(AdvancedStateModelBlockerCode.TRANSITION_ROW_SUM_INVALID)
    if any(
        item.observation_count < thresholds.minimum_duration_observations
        for item in candidate.duration_evidence
    ):
        blockers.append(AdvancedStateModelBlockerCode.DURATION_EVIDENCE_INSUFFICIENT)

    metrics = candidate.oos_metrics
    if metrics.transition_accuracy < thresholds.minimum_transition_accuracy:
        blockers.append(AdvancedStateModelBlockerCode.OOS_TRANSITION_ACCURACY_BELOW_MINIMUM)
    if metrics.log_loss > thresholds.maximum_log_loss:
        blockers.append(AdvancedStateModelBlockerCode.OOS_LOG_LOSS_ABOVE_MAXIMUM)
    if metrics.calibration_error > thresholds.maximum_calibration_error:
        blockers.append(AdvancedStateModelBlockerCode.OOS_CALIBRATION_ABOVE_MAXIMUM)
    baseline_transition_accuracy = (
        baseline_shortfall.metric_value("transition_accuracy")
        if baseline_shortfall is not None
        else None
    )
    baseline_log_loss = (
        baseline_shortfall.metric_value("log_loss") if baseline_shortfall is not None else None
    )
    baseline_calibration_error = (
        baseline_shortfall.metric_value("calibration_error")
        if baseline_shortfall is not None
        else None
    )
    if (
        baseline_transition_accuracy is None
        or baseline_log_loss is None
        or baseline_calibration_error is None
    ):
        blockers.append(AdvancedStateModelBlockerCode.BASELINE_BINDING_MISMATCH)
    elif (
        metrics.transition_accuracy <= baseline_transition_accuracy
        or metrics.log_loss >= baseline_log_loss
        or metrics.calibration_error >= baseline_calibration_error
    ):
        blockers.append(AdvancedStateModelBlockerCode.BASELINE_COMPARISON_NOT_IMPROVED)

    if candidate.policy_reaction is None:
        blockers.append(AdvancedStateModelBlockerCode.POLICY_TARGET_CONTRACT_MISSING)
    else:
        input_versions = {
            (item.dataset_key, item.input_version) for item in candidate.input_references
        }
        target_versions = {
            (target.dataset_key, target.input_version)
            for target in candidate.policy_reaction.targets
        }
        if not target_versions.issubset(input_versions):
            blockers.append(AdvancedStateModelBlockerCode.POLICY_TARGET_INPUT_MISMATCH)

    if candidate.acceptance_threshold_version != thresholds.threshold_version:
        blockers.append(AdvancedStateModelBlockerCode.ACCEPTANCE_THRESHOLD_VERSION_MISMATCH)
    if not thresholds.activated_at <= evaluated_at < thresholds.valid_until:
        blockers.append(AdvancedStateModelBlockerCode.ACCEPTANCE_THRESHOLDS_INACTIVE)
    governance = candidate.governance_policy
    if not governance.activated_at <= evaluated_at < governance.valid_until:
        blockers.append(AdvancedStateModelBlockerCode.GOVERNANCE_POLICY_INACTIVE)
    return _assessment(candidate, evaluated_at=evaluated_at, blockers=blockers)


__all__ = [
    "AdvancedStateMethodology",
    "AdvancedStateModelAcceptanceThresholds",
    "AdvancedStateModelAssessment",
    "AdvancedStateModelAssessmentStatus",
    "AdvancedStateModelBlockerCode",
    "AdvancedStateModelCandidateEvidence",
    "AdvancedStateModelGovernancePolicy",
    "EconomicStateLabel",
    "ExternalArtifactAttestation",
    "ExternalStateModelArtifact",
    "InvalidationDirection",
    "PolicyReactionSpecification",
    "PolicyTargetDefinition",
    "SimpleBaselineComparisonEvidence",
    "StateDurationEvidence",
    "StateLabelProtocol",
    "StateModelInputReference",
    "StateModelInvalidationRule",
    "StateModelLifecycleStatus",
    "StateModelOOSMetrics",
    "StateModelPITManifestEvidence",
    "StateModelRetirementEvidence",
    "StateProbability",
    "StateProbabilityDistribution",
    "StateTransitionMatrixEvidence",
    "StateTransitionRow",
    "evaluate_advanced_state_model_evidence",
]
