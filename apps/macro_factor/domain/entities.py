"""Immutable contracts for externally calculated R3 macro-factor research.

This module intentionally contains no estimator or training implementation.
It validates evidence produced by an external research runner and keeps every
accepted result research-only until a separate, future promotion flow exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum


def _require_text(value: str, field_name: str, *, maximum: int = 255) -> None:
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


class MacroTargetFamily(str, Enum):
    """Economic family of one governed macro target."""

    GROWTH = "growth"
    INFLATION = "inflation"
    RATE = "rate"
    CREDIT = "credit"
    LIQUIDITY = "liquidity"
    FX = "fx"


class FactorOutputRole(str, Enum):
    """Temporal meaning of one macro-factor output."""

    CURRENT_STATE = "current_state"
    FORWARD_EXPECTATION = "forward_expectation"


class ProxyAssetKind(str, Enum):
    """Semantics of a candidate high-frequency proxy asset."""

    SPOT = "spot"
    ETF = "etf"
    CONTINUOUS_FUTURE = "continuous_future"
    RATE = "rate"
    FX = "fx"
    OTHER = "other"


class SampleSegment(str, Enum):
    """Required model-evaluation sample partitions."""

    IN_SAMPLE = "in_sample"
    VALIDATION = "validation"
    OUT_OF_SAMPLE = "out_of_sample"


class ComparisonOperator(str, Enum):
    """Operator used by a versioned invalidation rule."""

    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


class FactorLifecycleStatus(str, Enum):
    """Allowed lifecycle states before any production promotion capability."""

    RESEARCH_ONLY = "research_only"
    RETIRED = "retired"


class MacroFactorAssessmentStatus(str, Enum):
    """Outcome of validating one external R3 result."""

    ACCEPTED = "accepted"
    BLOCKED = "blocked"


class MacroFactorBlockerCode(str, Enum):
    """Stable fail-closed reasons emitted by the R3 evidence gate."""

    EXTERNAL_RESULT_MISSING = "external_result_missing"
    PIT_MANIFEST_MISSING = "pit_manifest_missing"
    PIT_MANIFEST_UNVERIFIED = "pit_manifest_unverified"
    PIT_MANIFEST_MISMATCH = "pit_manifest_mismatch"
    PIT_MANIFEST_FROM_FUTURE = "pit_manifest_from_future"
    PIT_MANIFEST_SCOPE_INCOMPLETE = "pit_manifest_scope_incomplete"
    EXTERNAL_EVIDENCE_FROM_FUTURE = "external_evidence_from_future"
    EVIDENCE_TIMELINE_INVALID = "evidence_timeline_invalid"


@dataclass(frozen=True)
class MacroTargetDefinition:
    """Versioned definition of the macro variable being replicated or nowcast."""

    target_code: str
    family: MacroTargetFamily
    output_role: FactorOutputRole
    dataset_key: str
    business_key: str
    unit: str
    frequency: str
    transformation_version: str
    horizon_periods: int
    horizon_unit: str

    def __post_init__(self) -> None:
        _require_token(self.target_code, "MacroTargetDefinition.target_code")
        if not isinstance(self.family, MacroTargetFamily):
            raise ValueError("MacroTargetDefinition.family is invalid")
        if not isinstance(self.output_role, FactorOutputRole):
            raise ValueError("MacroTargetDefinition.output_role is invalid")
        for name in (
            "dataset_key",
            "business_key",
            "unit",
            "frequency",
            "transformation_version",
            "horizon_unit",
        ):
            _require_token(str(getattr(self, name)), f"MacroTargetDefinition.{name}")
        _require_positive_int(self.horizon_periods, "MacroTargetDefinition.horizon_periods")


@dataclass(frozen=True)
class ProxyAssetDefinition:
    """One candidate proxy with explicit dataset and transformation lineage."""

    asset_code: str
    dataset_key: str
    business_key: str
    kind: ProxyAssetKind
    frequency: str
    transformation_version: str
    continuous_roll_policy_version: str = ""

    def __post_init__(self) -> None:
        for name in (
            "asset_code",
            "dataset_key",
            "business_key",
            "frequency",
            "transformation_version",
        ):
            _require_token(str(getattr(self, name)), f"ProxyAssetDefinition.{name}")
        if not isinstance(self.kind, ProxyAssetKind):
            raise ValueError("ProxyAssetDefinition.kind is invalid")
        has_roll_policy = bool(self.continuous_roll_policy_version.strip())
        if self.kind is ProxyAssetKind.CONTINUOUS_FUTURE and not has_roll_policy:
            raise ValueError("continuous futures require a roll policy version")
        if self.kind is not ProxyAssetKind.CONTINUOUS_FUTURE and has_roll_policy:
            raise ValueError("roll policy version is only valid for continuous futures")


@dataclass(frozen=True)
class PITDatasetSlice:
    """Exact PIT fact versions covering one target or proxy business key."""

    dataset_key: str
    business_key: str
    version_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        _require_token(self.dataset_key, "PITDatasetSlice.dataset_key")
        _require_text(self.business_key, "PITDatasetSlice.business_key")
        if not self.version_ids:
            raise ValueError("PITDatasetSlice.version_ids cannot be empty")
        for version_id in self.version_ids:
            _require_positive_int(version_id, "PITDatasetSlice.version_id")
        if len(self.version_ids) != len(set(self.version_ids)):
            raise ValueError("PITDatasetSlice.version_ids must be unique")


@dataclass(frozen=True)
class PITManifestEvidence:
    """Application-facing projection of canonical Data Center PIT evidence."""

    manifest_id: str
    manifest_hash: str
    as_of_time: datetime
    knowledge_scope: str
    calendar_version: str
    slices: tuple[PITDatasetSlice, ...]
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    is_verified: bool

    def __post_init__(self) -> None:
        _require_token(self.manifest_id, "PITManifestEvidence.manifest_id")
        _require_sha256(self.manifest_hash, "PITManifestEvidence.manifest_hash")
        _require_aware(self.as_of_time, "PITManifestEvidence.as_of_time")
        _require_token(self.knowledge_scope, "PITManifestEvidence.knowledge_scope")
        _require_token(self.calendar_version, "PITManifestEvidence.calendar_version")
        _require_finite(self.coverage_ratio, "PITManifestEvidence.coverage_ratio")
        if not Decimal("0") <= self.coverage_ratio <= Decimal("1"):
            raise ValueError("PITManifestEvidence.coverage_ratio must be between zero and one")
        for name in ("missing_count", "estimated_count", "unknown_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"PITManifestEvidence.{name} cannot be negative")
        if not isinstance(self.is_verified, bool):
            raise ValueError("PITManifestEvidence.is_verified must be a boolean")
        identities = tuple((item.dataset_key, item.business_key) for item in self.slices)
        if len(identities) != len(set(identities)):
            raise ValueError("PIT manifest slices must have unique dataset/business identities")

    @property
    def is_complete(self) -> bool:
        """Return whether coverage contains only fully verified fact versions."""

        return (
            self.is_verified
            and bool(self.slices)
            and self.coverage_ratio == Decimal("1")
            and self.missing_count == 0
            and self.estimated_count == 0
            and self.unknown_count == 0
        )

    @property
    def slice_identities(self) -> frozenset[tuple[str, str]]:
        """Return immutable dataset/business identities sealed by the manifest."""

        return frozenset((item.dataset_key, item.business_key) for item in self.slices)


@dataclass(frozen=True)
class ReproducibilityEvidence:
    """Exact code, dependency and parameter versions used by the external run."""

    code_version: str
    dependency_lock_hash: str
    parameter_version: str
    parameter_hash: str

    def __post_init__(self) -> None:
        _require_token(self.code_version, "ReproducibilityEvidence.code_version")
        _require_sha256(
            self.dependency_lock_hash,
            "ReproducibilityEvidence.dependency_lock_hash",
        )
        _require_token(self.parameter_version, "ReproducibilityEvidence.parameter_version")
        _require_sha256(self.parameter_hash, "ReproducibilityEvidence.parameter_hash")


@dataclass(frozen=True)
class SampleWindow:
    """Closed date window for one research sample partition."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("SampleWindow.start cannot follow end")


@dataclass(frozen=True)
class WalkForwardFold:
    """One ordered train/validation/OOS walk-forward fold."""

    fold_id: str
    training: SampleWindow
    validation: SampleWindow
    out_of_sample: SampleWindow

    def __post_init__(self) -> None:
        _require_token(self.fold_id, "WalkForwardFold.fold_id")
        if self.training.end >= self.validation.start:
            raise ValueError("walk-forward training must precede validation")
        if self.validation.end >= self.out_of_sample.start:
            raise ValueError("walk-forward validation must precede out-of-sample")


def _has_embargo(left: SampleWindow, right: SampleWindow, embargo_days: int) -> bool:
    return (right.start - left.end).days > embargo_days


@dataclass(frozen=True)
class TemporalSplitSpec:
    """Versioned train/validation/OOS, walk-forward and embargo policy."""

    policy_version: str
    training: SampleWindow
    validation: SampleWindow
    out_of_sample: SampleWindow
    walk_forward_folds: tuple[WalkForwardFold, ...]
    embargo_days: int

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "TemporalSplitSpec.policy_version")
        _require_positive_int(self.embargo_days, "TemporalSplitSpec.embargo_days")
        if not _has_embargo(self.training, self.validation, self.embargo_days):
            raise ValueError("training/validation embargo is missing")
        if not _has_embargo(self.validation, self.out_of_sample, self.embargo_days):
            raise ValueError("validation/out-of-sample embargo is missing")
        if not self.walk_forward_folds:
            raise ValueError("TemporalSplitSpec.walk_forward_folds cannot be empty")
        fold_ids = tuple(fold.fold_id for fold in self.walk_forward_folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("walk-forward fold identities must be unique")
        for fold in self.walk_forward_folds:
            if not _has_embargo(fold.training, fold.validation, self.embargo_days):
                raise ValueError(f"walk-forward fold {fold.fold_id} lacks train embargo")
            if not _has_embargo(fold.validation, fold.out_of_sample, self.embargo_days):
                raise ValueError(f"walk-forward fold {fold.fold_id} lacks OOS embargo")


@dataclass(frozen=True)
class ExternalLassoSelectionEvidence:
    """Externally computed nested-CV Lasso selection evidence.

    The only accepted origin is ``external_precomputed``.  This App validates
    the artifact and never fits, tunes or fabricates a Lasso model.
    """

    evidence_id: str
    producer_ref: str
    produced_at: datetime
    computation_origin: str
    estimator: str
    validation_method: str
    inner_fold_count: int
    outer_fold_count: int
    alpha_grid: tuple[Decimal, ...]
    selected_alpha: Decimal
    optimization_metric: str
    coefficient_path_hash: str
    selection_report_hash: str
    selected_asset_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "ExternalLassoSelectionEvidence.evidence_id")
        _require_text(self.producer_ref, "ExternalLassoSelectionEvidence.producer_ref")
        _require_aware(self.produced_at, "ExternalLassoSelectionEvidence.produced_at")
        if self.computation_origin != "external_precomputed":
            raise ValueError("Lasso evidence must be external_precomputed")
        if self.estimator != "lasso":
            raise ValueError("external estimator must be lasso")
        if self.validation_method != "nested_cv":
            raise ValueError("Lasso validation_method must be nested_cv")
        if self.inner_fold_count < 2 or self.outer_fold_count < 2:
            raise ValueError("nested CV requires at least two inner and outer folds")
        if not self.alpha_grid:
            raise ValueError("Lasso alpha_grid cannot be empty")
        for alpha in self.alpha_grid:
            _require_finite(alpha, "ExternalLassoSelectionEvidence.alpha")
            if alpha <= 0:
                raise ValueError("Lasso alpha values must be positive")
        if len(self.alpha_grid) != len(set(self.alpha_grid)):
            raise ValueError("Lasso alpha_grid values must be unique")
        _require_finite(self.selected_alpha, "ExternalLassoSelectionEvidence.selected_alpha")
        if self.selected_alpha not in self.alpha_grid:
            raise ValueError("selected_alpha must be present in alpha_grid")
        _require_token(
            self.optimization_metric,
            "ExternalLassoSelectionEvidence.optimization_metric",
        )
        _require_sha256(
            self.coefficient_path_hash,
            "ExternalLassoSelectionEvidence.coefficient_path_hash",
        )
        _require_sha256(
            self.selection_report_hash,
            "ExternalLassoSelectionEvidence.selection_report_hash",
        )
        if not self.selected_asset_codes:
            raise ValueError("Lasso must select at least one proxy asset")
        for asset_code in self.selected_asset_codes:
            _require_token(asset_code, "ExternalLassoSelectionEvidence.selected_asset_code")
        if len(self.selected_asset_codes) != len(set(self.selected_asset_codes)):
            raise ValueError("selected proxy assets must be unique")


@dataclass(frozen=True)
class EvaluationMetrics:
    """R2, IC, stability, turnover and cost for one sample segment."""

    segment: SampleSegment
    sample_count: int
    r_squared: Decimal
    adjusted_r_squared: Decimal
    information_coefficient: Decimal
    stability_score: Decimal
    turnover: Decimal
    transaction_cost: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.segment, SampleSegment):
            raise ValueError("EvaluationMetrics.segment is invalid")
        _require_positive_int(self.sample_count, "EvaluationMetrics.sample_count")
        for name in (
            "r_squared",
            "adjusted_r_squared",
            "information_coefficient",
            "stability_score",
            "turnover",
            "transaction_cost",
        ):
            _require_finite(getattr(self, name), f"EvaluationMetrics.{name}")
        if self.r_squared > 1 or self.adjusted_r_squared > 1:
            raise ValueError("R-squared metrics cannot exceed one")
        if not Decimal("-1") <= self.information_coefficient <= Decimal("1"):
            raise ValueError("information_coefficient must be between -1 and 1")
        if not Decimal("0") <= self.stability_score <= Decimal("1"):
            raise ValueError("stability_score must be between zero and one")
        if self.turnover < 0 or self.transaction_cost < 0:
            raise ValueError("turnover and transaction_cost cannot be negative")


@dataclass(frozen=True)
class ModelEvaluationEvidence:
    """Required in-sample, validation and OOS performance evidence."""

    in_sample: EvaluationMetrics
    validation: EvaluationMetrics
    out_of_sample: EvaluationMetrics
    benchmark_version: str
    cost_model_version: str
    bic: Decimal
    statistical_significance_summary: str
    statistical_significance_evidence_ref: str
    economic_interpretation: str
    evidence_hash: str

    def __post_init__(self) -> None:
        expected = (
            (self.in_sample, SampleSegment.IN_SAMPLE),
            (self.validation, SampleSegment.VALIDATION),
            (self.out_of_sample, SampleSegment.OUT_OF_SAMPLE),
        )
        if any(metric.segment is not segment for metric, segment in expected):
            raise ValueError("evaluation metrics are assigned to the wrong sample segment")
        _require_token(self.benchmark_version, "ModelEvaluationEvidence.benchmark_version")
        _require_token(self.cost_model_version, "ModelEvaluationEvidence.cost_model_version")
        _require_finite(self.bic, "ModelEvaluationEvidence.bic")
        _require_text(
            self.statistical_significance_summary,
            "ModelEvaluationEvidence.statistical_significance_summary",
            maximum=2_000,
        )
        _require_text(
            self.statistical_significance_evidence_ref,
            "ModelEvaluationEvidence.statistical_significance_evidence_ref",
            maximum=500,
        )
        _require_text(
            self.economic_interpretation,
            "ModelEvaluationEvidence.economic_interpretation",
            maximum=2_000,
        )
        _require_sha256(self.evidence_hash, "ModelEvaluationEvidence.evidence_hash")


@dataclass(frozen=True)
class FactorWeight:
    """Selected proxy coefficient and factor-mimicking portfolio weight."""

    asset_code: str
    lasso_coefficient: Decimal
    factor_weight: Decimal

    def __post_init__(self) -> None:
        _require_token(self.asset_code, "FactorWeight.asset_code")
        _require_finite(self.lasso_coefficient, "FactorWeight.lasso_coefficient")
        _require_finite(self.factor_weight, "FactorWeight.factor_weight")
        if self.lasso_coefficient == 0:
            raise ValueError("selected proxy lasso_coefficient cannot be zero")


def calculate_factor_weight_hash(
    *,
    factor_version: str,
    calculated_at: datetime,
    weights: tuple[FactorWeight, ...],
) -> str:
    """Return the canonical digest of one immutable factor-weight version."""

    _require_token(factor_version, "factor_version")
    _require_aware(calculated_at, "calculated_at")
    payload = {
        "factor_version": factor_version,
        "calculated_at": calculated_at.astimezone(UTC).isoformat(),
        "weights": [
            {
                "asset_code": weight.asset_code,
                "lasso_coefficient": _decimal_text(weight.lasso_coefficient),
                "factor_weight": _decimal_text(weight.factor_weight),
            }
            for weight in sorted(weights, key=lambda item: item.asset_code)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FactorWeightVersion:
    """Immutable selected-asset weights for one named factor version."""

    factor_version: str
    calculated_at: datetime
    weights: tuple[FactorWeight, ...]
    weight_hash: str

    def __post_init__(self) -> None:
        _require_token(self.factor_version, "FactorWeightVersion.factor_version")
        _require_aware(self.calculated_at, "FactorWeightVersion.calculated_at")
        if not self.weights:
            raise ValueError("FactorWeightVersion.weights cannot be empty")
        asset_codes = tuple(weight.asset_code for weight in self.weights)
        if len(asset_codes) != len(set(asset_codes)):
            raise ValueError("factor weights must have unique asset codes")
        _require_sha256(self.weight_hash, "FactorWeightVersion.weight_hash")
        expected = calculate_factor_weight_hash(
            factor_version=self.factor_version,
            calculated_at=self.calculated_at,
            weights=self.weights,
        )
        if self.weight_hash.lower() != expected:
            raise ValueError("FactorWeightVersion.weight_hash does not match content")


@dataclass(frozen=True)
class InvalidationRule:
    """Versioned rule that can invalidate a deteriorating factor."""

    rule_id: str
    metric_name: str
    operator: ComparisonOperator
    threshold: Decimal
    consecutive_windows: int
    observation_window: str
    rationale: str

    def __post_init__(self) -> None:
        _require_token(self.rule_id, "InvalidationRule.rule_id")
        _require_token(self.metric_name, "InvalidationRule.metric_name")
        if not isinstance(self.operator, ComparisonOperator):
            raise ValueError("InvalidationRule.operator is invalid")
        _require_finite(self.threshold, "InvalidationRule.threshold")
        _require_positive_int(self.consecutive_windows, "InvalidationRule.consecutive_windows")
        _require_token(self.observation_window, "InvalidationRule.observation_window")
        _require_text(self.rationale, "InvalidationRule.rationale", maximum=500)


@dataclass(frozen=True)
class RetirementPolicy:
    """Governed invalidation and retirement policy for one factor result."""

    policy_version: str
    owner_ref: str
    evaluation_frequency: str
    retire_on_any: bool
    rules: tuple[InvalidationRule, ...]

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "RetirementPolicy.policy_version")
        _require_token(self.owner_ref, "RetirementPolicy.owner_ref")
        _require_token(self.evaluation_frequency, "RetirementPolicy.evaluation_frequency")
        if not isinstance(self.retire_on_any, bool):
            raise ValueError("RetirementPolicy.retire_on_any must be a boolean")
        if not self.rules:
            raise ValueError("RetirementPolicy.rules cannot be empty")
        rule_ids = tuple(rule.rule_id for rule in self.rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("retirement rule identities must be unique")


@dataclass(frozen=True)
class RetirementEvidence:
    """Append-only evidence that a research factor was retired."""

    event_id: str
    retired_at: datetime
    policy_version: str
    reason_codes: tuple[str, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_token(self.event_id, "RetirementEvidence.event_id")
        _require_aware(self.retired_at, "RetirementEvidence.retired_at")
        _require_token(self.policy_version, "RetirementEvidence.policy_version")
        if not self.reason_codes:
            raise ValueError("RetirementEvidence.reason_codes cannot be empty")
        for reason_code in self.reason_codes:
            _require_token(reason_code, "RetirementEvidence.reason_code")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("retirement reason codes must be unique")
        _require_sha256(self.evidence_hash, "RetirementEvidence.evidence_hash")


def _metric_payload(metric: EvaluationMetrics) -> dict[str, object]:
    return {
        "segment": metric.segment.value,
        "sample_count": metric.sample_count,
        "r_squared": _decimal_text(metric.r_squared),
        "adjusted_r_squared": _decimal_text(metric.adjusted_r_squared),
        "information_coefficient": _decimal_text(metric.information_coefficient),
        "stability_score": _decimal_text(metric.stability_score),
        "turnover": _decimal_text(metric.turnover),
        "transaction_cost": _decimal_text(metric.transaction_cost),
    }


def _window_payload(window: SampleWindow) -> dict[str, str]:
    return {"start": window.start.isoformat(), "end": window.end.isoformat()}


@dataclass(frozen=True)
class ExternalMacroFactorResearchResult:
    """Complete external R3 result accepted only as research evidence."""

    result_id: str
    factor_version: str
    target: MacroTargetDefinition
    candidates: tuple[ProxyAssetDefinition, ...]
    pit_manifest_id: str
    pit_manifest_hash: str
    reproducibility: ReproducibilityEvidence
    split: TemporalSplitSpec
    selection: ExternalLassoSelectionEvidence
    evaluation: ModelEvaluationEvidence
    weights: FactorWeightVersion
    retirement_policy: RetirementPolicy
    lifecycle_status: FactorLifecycleStatus
    retirement_evidence: RetirementEvidence | None
    research_only: bool = True
    must_not_use_for_decision: bool = True

    def __post_init__(self) -> None:
        _require_token(self.result_id, "ExternalMacroFactorResearchResult.result_id")
        _require_token(self.factor_version, "ExternalMacroFactorResearchResult.factor_version")
        _require_token(
            self.pit_manifest_id,
            "ExternalMacroFactorResearchResult.pit_manifest_id",
        )
        _require_sha256(
            self.pit_manifest_hash,
            "ExternalMacroFactorResearchResult.pit_manifest_hash",
        )
        if not self.candidates:
            raise ValueError("macro-factor candidate universe cannot be empty")
        candidate_codes = tuple(candidate.asset_code for candidate in self.candidates)
        if len(candidate_codes) != len(set(candidate_codes)):
            raise ValueError("macro-factor candidate asset codes must be unique")
        candidate_scopes = tuple(
            (candidate.dataset_key, candidate.business_key) for candidate in self.candidates
        )
        if len(candidate_scopes) != len(set(candidate_scopes)):
            raise ValueError("macro-factor candidate dataset scopes must be unique")
        selected_codes = self.selection.selected_asset_codes
        weight_codes = tuple(weight.asset_code for weight in self.weights.weights)
        if set(selected_codes) != set(weight_codes) or len(selected_codes) != len(weight_codes):
            raise ValueError("selected proxy assets must match factor weights exactly")
        if not set(selected_codes).issubset(set(candidate_codes)):
            raise ValueError("selected proxy assets must belong to the candidate universe")
        if self.weights.factor_version != self.factor_version:
            raise ValueError("factor weight version must match factor_version")
        if self.selection.outer_fold_count != len(self.split.walk_forward_folds):
            raise ValueError("nested CV outer folds must match walk-forward evidence")
        if self.weights.calculated_at < self.selection.produced_at:
            raise ValueError("factor weights cannot predate Lasso selection evidence")
        if not isinstance(self.lifecycle_status, FactorLifecycleStatus):
            raise ValueError("ExternalMacroFactorResearchResult.lifecycle_status is invalid")
        if self.lifecycle_status is FactorLifecycleStatus.RETIRED:
            if self.retirement_evidence is None:
                raise ValueError("retired factors require retirement evidence")
            if self.retirement_evidence.policy_version != self.retirement_policy.policy_version:
                raise ValueError("retirement evidence must reference the retirement policy")
            valid_reasons = {rule.rule_id for rule in self.retirement_policy.rules}
            if not set(self.retirement_evidence.reason_codes).issubset(valid_reasons):
                raise ValueError("retirement evidence references unknown invalidation rules")
        elif self.retirement_evidence is not None:
            raise ValueError("non-retired factors cannot carry retirement evidence")
        if self.research_only is not True or self.must_not_use_for_decision is not True:
            raise ValueError("macro-factor results must remain research-only and decision-blocked")

    def canonical_payload(self) -> dict[str, object]:
        """Return every model, data, split, metric and lifecycle field canonically."""

        retirement: dict[str, object] | None = None
        if self.retirement_evidence is not None:
            retirement = {
                "event_id": self.retirement_evidence.event_id,
                "retired_at": self.retirement_evidence.retired_at.astimezone(UTC).isoformat(),
                "policy_version": self.retirement_evidence.policy_version,
                "reason_codes": list(self.retirement_evidence.reason_codes),
                "evidence_hash": self.retirement_evidence.evidence_hash,
            }
        return {
            "result_id": self.result_id,
            "factor_version": self.factor_version,
            "target": {
                "target_code": self.target.target_code,
                "family": self.target.family.value,
                "output_role": self.target.output_role.value,
                "dataset_key": self.target.dataset_key,
                "business_key": self.target.business_key,
                "unit": self.target.unit,
                "frequency": self.target.frequency,
                "transformation_version": self.target.transformation_version,
                "horizon_periods": self.target.horizon_periods,
                "horizon_unit": self.target.horizon_unit,
            },
            "candidates": [
                {
                    "asset_code": candidate.asset_code,
                    "dataset_key": candidate.dataset_key,
                    "business_key": candidate.business_key,
                    "kind": candidate.kind.value,
                    "frequency": candidate.frequency,
                    "transformation_version": candidate.transformation_version,
                    "continuous_roll_policy_version": (candidate.continuous_roll_policy_version),
                }
                for candidate in sorted(self.candidates, key=lambda item: item.asset_code)
            ],
            "pit_manifest_id": self.pit_manifest_id,
            "pit_manifest_hash": self.pit_manifest_hash,
            "reproducibility": {
                "code_version": self.reproducibility.code_version,
                "dependency_lock_hash": self.reproducibility.dependency_lock_hash,
                "parameter_version": self.reproducibility.parameter_version,
                "parameter_hash": self.reproducibility.parameter_hash,
            },
            "split": {
                "policy_version": self.split.policy_version,
                "training": _window_payload(self.split.training),
                "validation": _window_payload(self.split.validation),
                "out_of_sample": _window_payload(self.split.out_of_sample),
                "walk_forward_folds": [
                    {
                        "fold_id": fold.fold_id,
                        "training": _window_payload(fold.training),
                        "validation": _window_payload(fold.validation),
                        "out_of_sample": _window_payload(fold.out_of_sample),
                    }
                    for fold in self.split.walk_forward_folds
                ],
                "embargo_days": self.split.embargo_days,
            },
            "selection": {
                "evidence_id": self.selection.evidence_id,
                "producer_ref": self.selection.producer_ref,
                "produced_at": self.selection.produced_at.astimezone(UTC).isoformat(),
                "computation_origin": self.selection.computation_origin,
                "estimator": self.selection.estimator,
                "validation_method": self.selection.validation_method,
                "inner_fold_count": self.selection.inner_fold_count,
                "outer_fold_count": self.selection.outer_fold_count,
                "alpha_grid": [_decimal_text(value) for value in self.selection.alpha_grid],
                "selected_alpha": _decimal_text(self.selection.selected_alpha),
                "optimization_metric": self.selection.optimization_metric,
                "coefficient_path_hash": self.selection.coefficient_path_hash,
                "selection_report_hash": self.selection.selection_report_hash,
                "selected_asset_codes": list(self.selection.selected_asset_codes),
            },
            "evaluation": {
                "in_sample": _metric_payload(self.evaluation.in_sample),
                "validation": _metric_payload(self.evaluation.validation),
                "out_of_sample": _metric_payload(self.evaluation.out_of_sample),
                "benchmark_version": self.evaluation.benchmark_version,
                "cost_model_version": self.evaluation.cost_model_version,
                "bic": _decimal_text(self.evaluation.bic),
                "statistical_significance_summary": (
                    self.evaluation.statistical_significance_summary
                ),
                "statistical_significance_evidence_ref": (
                    self.evaluation.statistical_significance_evidence_ref
                ),
                "economic_interpretation": self.evaluation.economic_interpretation,
                "evidence_hash": self.evaluation.evidence_hash,
            },
            "weights": {
                "factor_version": self.weights.factor_version,
                "calculated_at": self.weights.calculated_at.astimezone(UTC).isoformat(),
                "weight_hash": self.weights.weight_hash,
                "values": [
                    {
                        "asset_code": weight.asset_code,
                        "lasso_coefficient": _decimal_text(weight.lasso_coefficient),
                        "factor_weight": _decimal_text(weight.factor_weight),
                    }
                    for weight in sorted(
                        self.weights.weights,
                        key=lambda item: item.asset_code,
                    )
                ],
            },
            "retirement_policy": {
                "policy_version": self.retirement_policy.policy_version,
                "owner_ref": self.retirement_policy.owner_ref,
                "evaluation_frequency": self.retirement_policy.evaluation_frequency,
                "retire_on_any": self.retirement_policy.retire_on_any,
                "rules": [
                    {
                        "rule_id": rule.rule_id,
                        "metric_name": rule.metric_name,
                        "operator": rule.operator.value,
                        "threshold": _decimal_text(rule.threshold),
                        "consecutive_windows": rule.consecutive_windows,
                        "observation_window": rule.observation_window,
                        "rationale": rule.rationale,
                    }
                    for rule in sorted(
                        self.retirement_policy.rules,
                        key=lambda item: item.rule_id,
                    )
                ],
            },
            "lifecycle_status": self.lifecycle_status.value,
            "retirement_evidence": retirement,
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
        }

    @property
    def canonical_json(self) -> str:
        """Return stable JSON used for persistence and content hashing."""

        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def content_hash(self) -> str:
        """Return a digest sealing the full external research result."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_record(self) -> ImmutableMacroFactorResearchRecord:
        """Project the validated result into its append-only persistence record."""

        return ImmutableMacroFactorResearchRecord(
            result_id=self.result_id,
            factor_version=self.factor_version,
            target_code=self.target.target_code,
            evidence_produced_at=self.weights.calculated_at,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            code_version=self.reproducibility.code_version,
            parameter_version=self.reproducibility.parameter_version,
            external_evidence_id=self.selection.evidence_id,
            lifecycle_status=self.lifecycle_status,
            payload_json=self.canonical_json,
            content_hash=self.content_hash,
            research_only=True,
            must_not_use_for_decision=True,
        )


@dataclass(frozen=True)
class ImmutableMacroFactorResearchRecord:
    """Append-only storage projection of one complete R3 result."""

    result_id: str
    factor_version: str
    target_code: str
    evidence_produced_at: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    code_version: str
    parameter_version: str
    external_evidence_id: str
    lifecycle_status: FactorLifecycleStatus
    payload_json: str
    content_hash: str
    research_only: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "factor_version",
            "target_code",
            "pit_manifest_id",
            "code_version",
            "parameter_version",
            "external_evidence_id",
        ):
            _require_token(str(getattr(self, name)), f"ImmutableRecord.{name}")
        _require_aware(self.evidence_produced_at, "ImmutableRecord.evidence_produced_at")
        _require_sha256(self.pit_manifest_hash, "ImmutableRecord.pit_manifest_hash")
        _require_text(self.payload_json, "ImmutableRecord.payload_json", maximum=1_000_000)
        _require_sha256(self.content_hash, "ImmutableRecord.content_hash")
        expected_hash = hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()
        if self.content_hash.lower() != expected_hash:
            raise ValueError("ImmutableRecord.content_hash does not match payload")
        if not isinstance(self.lifecycle_status, FactorLifecycleStatus):
            raise ValueError("ImmutableRecord.lifecycle_status is invalid")
        if self.research_only is not True or self.must_not_use_for_decision is not True:
            raise ValueError("macro-factor records must remain research-only and decision-blocked")


@dataclass(frozen=True)
class MacroFactorResearchAssessment:
    """Fail-closed assessment; accepted still means research-only."""

    status: MacroFactorAssessmentStatus
    external_evidence_id: str
    factor_version: str | None
    assessed_at: datetime
    blocked_reasons: tuple[MacroFactorBlockerCode, ...]
    record: ImmutableMacroFactorResearchRecord | None
    research_only: bool = True
    must_not_use_for_decision: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.status, MacroFactorAssessmentStatus):
            raise ValueError("MacroFactorResearchAssessment.status is invalid")
        _require_token(
            self.external_evidence_id,
            "MacroFactorResearchAssessment.external_evidence_id",
        )
        _require_aware(self.assessed_at, "MacroFactorResearchAssessment.assessed_at")
        if self.status is MacroFactorAssessmentStatus.ACCEPTED:
            if self.record is None or self.blocked_reasons:
                raise ValueError("accepted assessment requires a record and no blockers")
        elif self.record is not None or not self.blocked_reasons:
            raise ValueError("blocked assessment requires blockers and no record")
        if self.research_only is not True or self.must_not_use_for_decision is not True:
            raise ValueError("macro-factor assessments cannot authorize decisions")


def validate_external_macro_factor_result(
    result: ExternalMacroFactorResearchResult,
    manifest: PITManifestEvidence,
    *,
    assessed_at: datetime,
) -> tuple[MacroFactorBlockerCode, ...]:
    """Validate canonical PIT scope and external-evidence chronology."""

    _require_aware(assessed_at, "assessed_at")
    blockers: list[MacroFactorBlockerCode] = []
    if (
        result.pit_manifest_id != manifest.manifest_id
        or result.pit_manifest_hash.lower() != manifest.manifest_hash.lower()
    ):
        blockers.append(MacroFactorBlockerCode.PIT_MANIFEST_MISMATCH)
    if not manifest.is_verified:
        blockers.append(MacroFactorBlockerCode.PIT_MANIFEST_UNVERIFIED)
    required_scopes = {
        (result.target.dataset_key, result.target.business_key),
        *((candidate.dataset_key, candidate.business_key) for candidate in result.candidates),
    }
    if not manifest.is_complete or not required_scopes.issubset(manifest.slice_identities):
        blockers.append(MacroFactorBlockerCode.PIT_MANIFEST_SCOPE_INCOMPLETE)
    if manifest.as_of_time > assessed_at:
        blockers.append(MacroFactorBlockerCode.PIT_MANIFEST_FROM_FUTURE)
    evidence_times = [result.selection.produced_at, result.weights.calculated_at]
    if result.retirement_evidence is not None:
        evidence_times.append(result.retirement_evidence.retired_at)
    if any(value > assessed_at for value in evidence_times):
        blockers.append(MacroFactorBlockerCode.EXTERNAL_EVIDENCE_FROM_FUTURE)
    if result.selection.produced_at < manifest.as_of_time:
        blockers.append(MacroFactorBlockerCode.EVIDENCE_TIMELINE_INVALID)
    return tuple(dict.fromkeys(blockers))


__all__ = [
    "ComparisonOperator",
    "EvaluationMetrics",
    "ExternalLassoSelectionEvidence",
    "ExternalMacroFactorResearchResult",
    "FactorLifecycleStatus",
    "FactorOutputRole",
    "FactorWeight",
    "FactorWeightVersion",
    "ImmutableMacroFactorResearchRecord",
    "InvalidationRule",
    "MacroFactorAssessmentStatus",
    "MacroFactorBlockerCode",
    "MacroFactorResearchAssessment",
    "MacroTargetDefinition",
    "MacroTargetFamily",
    "ModelEvaluationEvidence",
    "PITDatasetSlice",
    "PITManifestEvidence",
    "ProxyAssetDefinition",
    "ProxyAssetKind",
    "ReproducibilityEvidence",
    "RetirementEvidence",
    "RetirementPolicy",
    "SampleSegment",
    "SampleWindow",
    "TemporalSplitSpec",
    "WalkForwardFold",
    "calculate_factor_weight_hash",
    "validate_external_macro_factor_result",
]
