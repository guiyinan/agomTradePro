"""Evidence contract for proving a simple regime baseline is insufficient."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ShortfallDirection(str, Enum):
    """Direction in which an observed baseline metric proves shortfall."""

    ABOVE_MAXIMUM = "above_maximum"
    BELOW_MINIMUM = "below_minimum"


class BaselineEvidenceState(str, Enum):
    """Completeness state of one immutable baseline evaluation."""

    VERIFIED = "verified"
    MISSING = "missing"
    UNVERIFIED = "unverified"
    STALE = "stale"


class BaselineShortfallDecision(str, Enum):
    """Decision on whether advanced state-model research may be proposed."""

    PROVEN = "proven"
    NOT_PROVEN = "not_proven"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BaselineMetricCriterion:
    """Versioned acceptance criterion supplied by Research governance."""

    metric_key: str
    unit: str
    direction: ShortfallDirection
    threshold: Decimal

    def __post_init__(self) -> None:
        """Validate a bounded metric identifier and finite threshold."""

        _require_token(self.metric_key, "metric_key", maximum=80)
        _require_text(self.unit, "unit", maximum=40)
        if not isinstance(self.direction, ShortfallDirection):
            raise ValueError("baseline metric direction is invalid")
        _require_finite(self.threshold, "threshold")

    def proves_shortfall(self, value: Decimal) -> bool:
        """Return whether one observed metric crosses the governed boundary."""

        _require_finite(value, "metric value")
        if self.direction is ShortfallDirection.ABOVE_MAXIMUM:
            return value > self.threshold
        return value < self.threshold


@dataclass(frozen=True)
class BaselineEvaluationSpecification:
    """Frozen evaluation window and criteria for one simple baseline version."""

    specification_version: str
    baseline_key: str
    baseline_version: str
    pit_manifest_id: str
    window_start: datetime
    window_end: datetime
    minimum_observations: int
    criteria: tuple[BaselineMetricCriterion, ...]
    approved_by: str
    activated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject unversioned, duplicated, or time-invalid specifications."""

        for field_name, text_value in (
            ("specification_version", self.specification_version),
            ("baseline_key", self.baseline_key),
            ("baseline_version", self.baseline_version),
            ("pit_manifest_id", self.pit_manifest_id),
            ("approved_by", self.approved_by),
        ):
            _require_token(text_value, field_name, maximum=120)
        for field_name, timestamp in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("activated_at", self.activated_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(timestamp, field_name)
        if self.window_end <= self.window_start:
            raise ValueError("baseline evaluation window_end must follow window_start")
        if self.valid_until <= self.activated_at:
            raise ValueError("baseline specification valid_until must follow activated_at")
        if isinstance(self.minimum_observations, bool) or self.minimum_observations <= 0:
            raise ValueError("minimum_observations must be positive")
        if not self.criteria:
            raise ValueError("baseline evaluation requires at least one criterion")
        keys = [item.metric_key for item in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("baseline evaluation contains duplicate metric criteria")


@dataclass(frozen=True)
class BaselineMetricObservation:
    """One sample-out metric computed from the frozen PIT evaluation window."""

    metric_key: str
    unit: str
    value: Decimal

    def __post_init__(self) -> None:
        """Validate the observed metric without assigning economic meaning."""

        _require_token(self.metric_key, "metric_key", maximum=80)
        _require_text(self.unit, "unit", maximum=40)
        _require_finite(self.value, "value")


@dataclass(frozen=True)
class BaselineEvaluationEvidence:
    """Immutable, owner-attested output of one baseline evaluation run."""

    evaluation_id: str
    specification_version: str
    baseline_key: str
    baseline_version: str
    pit_manifest_id: str
    state: BaselineEvidenceState
    window_start: datetime
    window_end: datetime
    observation_count: int
    evaluated_at: datetime
    valid_until: datetime | None
    metrics: tuple[BaselineMetricObservation, ...]
    evidence_refs: tuple[str, ...]
    blocking_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate evidence identity, clocks, completeness, and provenance."""

        for field_name, text_value in (
            ("evaluation_id", self.evaluation_id),
            ("specification_version", self.specification_version),
            ("baseline_key", self.baseline_key),
            ("baseline_version", self.baseline_version),
            ("pit_manifest_id", self.pit_manifest_id),
        ):
            _require_token(text_value, field_name, maximum=120)
        for field_name, timestamp in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("evaluated_at", self.evaluated_at),
        ):
            _require_aware(timestamp, field_name)
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")
            if self.valid_until <= self.evaluated_at:
                raise ValueError("baseline evidence valid_until must follow evaluated_at")
        if self.window_end <= self.window_start:
            raise ValueError("baseline evidence window_end must follow window_start")
        if isinstance(self.observation_count, bool) or self.observation_count < 0:
            raise ValueError("baseline observation_count cannot be negative")
        metric_keys = [item.metric_key for item in self.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("baseline evidence contains duplicate metrics")
        if self.state is BaselineEvidenceState.VERIFIED:
            if self.valid_until is None:
                raise ValueError("verified baseline evidence requires valid_until")
            if not self.metrics or not self.evidence_refs:
                raise ValueError("verified baseline evidence requires metrics and references")
            if any(not value.strip() for value in self.evidence_refs):
                raise ValueError("baseline evidence references cannot be blank")
            if self.blocking_reason is not None:
                raise ValueError("verified baseline evidence cannot contain a blocker")
        elif self.blocking_reason is None or not self.blocking_reason.strip():
            raise ValueError("non-verified baseline evidence requires a blocker")


@dataclass(frozen=True)
class BaselineShortfallBlocker:
    """Stable reason why simple-baseline shortfall is not proven."""

    reason_code: str
    detail: str
    metric_key: str | None = None


@dataclass(frozen=True)
class BaselineShortfallReport:
    """Fail-closed result used by the R6 capability start gate."""

    specification_version: str
    evaluation_id: str
    decision: BaselineShortfallDecision
    can_propose_advanced_model_research: bool
    metric_results: tuple[tuple[str, bool], ...]
    blockers: tuple[BaselineShortfallBlocker, ...]


def evaluate_baseline_shortfall(
    *,
    specification: BaselineEvaluationSpecification,
    evidence: BaselineEvaluationEvidence,
    evaluated_at: datetime,
) -> BaselineShortfallReport:
    """Prove shortfall only from complete, current, specification-bound evidence."""

    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[BaselineShortfallBlocker] = []
    if evidence.evaluated_at > evaluated_at:
        raise ValueError("baseline evidence cannot be evaluated in the future")
    expected_identity = (
        specification.specification_version,
        specification.baseline_key,
        specification.baseline_version,
        specification.pit_manifest_id,
        specification.window_start,
        specification.window_end,
    )
    actual_identity = (
        evidence.specification_version,
        evidence.baseline_key,
        evidence.baseline_version,
        evidence.pit_manifest_id,
        evidence.window_start,
        evidence.window_end,
    )
    if actual_identity != expected_identity:
        raise ValueError("baseline evidence does not match the evaluation specification")
    if not specification.activated_at <= evaluated_at < specification.valid_until:
        blockers.append(
            BaselineShortfallBlocker(
                reason_code="state_model_baseline.specification_inactive",
                detail="baseline evaluation specification is not active",
            )
        )
    if evidence.state is not BaselineEvidenceState.VERIFIED:
        assert evidence.blocking_reason is not None
        blockers.append(
            BaselineShortfallBlocker(
                reason_code=f"state_model_baseline.evidence.{evidence.state.value}",
                detail=evidence.blocking_reason,
            )
        )
    elif evidence.valid_until is not None and evidence.valid_until <= evaluated_at:
        blockers.append(
            BaselineShortfallBlocker(
                reason_code="state_model_baseline.evidence.stale",
                detail="verified baseline evaluation evidence has expired",
            )
        )
    if evidence.observation_count < specification.minimum_observations:
        blockers.append(
            BaselineShortfallBlocker(
                reason_code="state_model_baseline.sample.insufficient",
                detail="baseline evaluation has fewer observations than required",
            )
        )

    observed_by_key = {item.metric_key: item for item in evidence.metrics}
    metric_results: list[tuple[str, bool]] = []
    for criterion in specification.criteria:
        observation = observed_by_key.get(criterion.metric_key)
        if observation is None:
            blockers.append(
                BaselineShortfallBlocker(
                    reason_code=f"state_model_baseline.metric.{criterion.metric_key}.missing",
                    detail="required baseline metric is missing",
                    metric_key=criterion.metric_key,
                )
            )
            continue
        if observation.unit != criterion.unit:
            raise ValueError(f"baseline metric {criterion.metric_key} unit mismatch")
        proves_shortfall = criterion.proves_shortfall(observation.value)
        metric_results.append((criterion.metric_key, proves_shortfall))

    if blockers:
        decision = BaselineShortfallDecision.BLOCKED
    elif all(result for _, result in metric_results):
        decision = BaselineShortfallDecision.PROVEN
    else:
        decision = BaselineShortfallDecision.NOT_PROVEN
    return BaselineShortfallReport(
        specification_version=specification.specification_version,
        evaluation_id=evidence.evaluation_id,
        decision=decision,
        can_propose_advanced_model_research=(decision is BaselineShortfallDecision.PROVEN),
        metric_results=tuple(metric_results),
        blockers=tuple(blockers),
    )


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank string")


def _require_token(value: str, field_name: str, *, maximum: int) -> None:
    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
