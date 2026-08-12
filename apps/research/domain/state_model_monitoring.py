"""Pure R6 monitoring contracts over owner-attested raw observations.

The module deliberately stops at an internal retirement-review recommendation.
It never retires a qualification, replaces Regime, publishes current state, or
authorizes a portfolio decision or execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256

from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_text(value: str, field_name: str, *, maximum: int = 300) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-blank text")


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _require_hash(value: object, field_name: str) -> None:
    if not _is_hash(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _hashes_equal(left: object, right: object) -> bool:
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and _is_hash(left)
        and _is_hash(right)
        and left.lower() == right.lower()
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def derive_r6_monitoring_period_id(
    *,
    period_calendar_id: str,
    period_calendar_version: str,
    period_start: datetime,
    period_end: datetime,
) -> str:
    """Derive one canonical monitoring-window identity from its exact calendar."""

    _require_token(period_calendar_id, "period_calendar_id")
    _require_token(period_calendar_version, "period_calendar_version")
    _require_aware(period_start, "period_start")
    _require_aware(period_end, "period_end")
    if period_start >= period_end:
        raise ValueError("R6 monitoring period window must be non-empty")
    return _hash_payload(
        {
            "schema": "r6-monitoring-period.v1",
            "period_calendar_id": period_calendar_id,
            "period_calendar_version": period_calendar_version,
            "period_start": _utc_text(period_start),
            "period_end": _utc_text(period_end),
        }
    )


class R6MonitoringMetricKey(str, Enum):
    """Required performance and policy-reaction monitoring facts."""

    TRANSITION_ACCURACY = "transition_accuracy"
    LOG_LOSS = "log_loss"
    CALIBRATION_ERROR = "calibration_error"
    DURATION_MAE = "duration_mae"
    DECISION_LOSS = "decision_loss"
    LABEL_STABILITY = "label_stability"
    POLICY_ADJUSTED_R_SQUARED = "policy_adjusted_r_squared"
    POLICY_RESIDUAL_AUTOCORRELATION_P_VALUE = "policy_residual_autocorrelation_p_value"
    POLICY_HETEROSKEDASTICITY_P_VALUE = "policy_heteroskedasticity_p_value"
    POLICY_PARAMETER_STABILITY_P_VALUE = "policy_parameter_stability_p_value"
    POLICY_CONDITION_NUMBER = "policy_condition_number"


REQUIRED_R6_MONITORING_METRICS: frozenset[R6MonitoringMetricKey] = frozenset(R6MonitoringMetricKey)

_UNIT_INTERVAL_METRICS: frozenset[R6MonitoringMetricKey] = frozenset(
    {
        R6MonitoringMetricKey.TRANSITION_ACCURACY,
        R6MonitoringMetricKey.LABEL_STABILITY,
        R6MonitoringMetricKey.POLICY_RESIDUAL_AUTOCORRELATION_P_VALUE,
        R6MonitoringMetricKey.POLICY_HETEROSKEDASTICITY_P_VALUE,
        R6MonitoringMetricKey.POLICY_PARAMETER_STABILITY_P_VALUE,
    }
)
_NON_NEGATIVE_METRICS: frozenset[R6MonitoringMetricKey] = frozenset(
    {
        R6MonitoringMetricKey.LOG_LOSS,
        R6MonitoringMetricKey.CALIBRATION_ERROR,
        R6MonitoringMetricKey.DURATION_MAE,
        R6MonitoringMetricKey.DECISION_LOSS,
    }
)


def _require_metric_domain(
    metric_key: R6MonitoringMetricKey,
    value: Decimal,
    field_name: str,
) -> None:
    """Enforce semantic numeric domains before threshold evaluation."""

    _require_finite(value, field_name)
    if metric_key in _UNIT_INTERVAL_METRICS and not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{field_name} must be within [0, 1]")
    if metric_key in _NON_NEGATIVE_METRICS and value < Decimal("0"):
        raise ValueError(f"{field_name} cannot be negative")
    if metric_key is R6MonitoringMetricKey.POLICY_CONDITION_NUMBER and value < Decimal("1"):
        raise ValueError(f"{field_name} must be at least one")
    if metric_key is R6MonitoringMetricKey.POLICY_ADJUSTED_R_SQUARED and value > Decimal("1"):
        raise ValueError(f"{field_name} cannot exceed one")


class R6MonitoringThresholdDirection(str, Enum):
    """Whether a healthy metric must stay at least or at most a threshold."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class R6MonitoringAssessmentStatus(str, Enum):
    """Research-only monitoring result with no lifecycle side effect."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


class R6MonitoringBlockerCode(str, Enum):
    """Stable fail-closed reasons for an R6 monitoring assessment."""

    ACTIVE_QUALIFICATION_MISSING = "r6_monitoring.active_qualification.missing"
    ACTIVE_QUALIFICATION_INVALID = "r6_monitoring.active_qualification.invalid"
    POLICY_MISSING = "r6_monitoring.policy.missing"
    POLICY_BINDING_MISMATCH = "r6_monitoring.policy.binding_mismatch"
    POLICY_HASH_MISMATCH = "r6_monitoring.policy.hash_mismatch"
    POLICY_FROM_FUTURE = "r6_monitoring.policy.from_future"
    POLICY_INACTIVE = "r6_monitoring.policy.inactive"
    POLICY_QUALIFICATION_CAUSALITY_INVALID = "r6_monitoring.policy.qualification_causality_invalid"
    OBSERVATIONS_MISSING = "r6_monitoring.observations.missing"
    OBSERVATION_IDENTITY_DUPLICATE = "r6_monitoring.observation.identity_duplicate"
    OBSERVATION_PERIOD_DUPLICATE = "r6_monitoring.observation.period_duplicate"
    OBSERVATION_PERIOD_ORDER_INVALID = "r6_monitoring.observation.period_order_invalid"
    OBSERVATION_PERIOD_ID_MISMATCH = "r6_monitoring.observation.period_id_mismatch"
    OBSERVATION_PERIOD_WINDOW_INVALID = "r6_monitoring.observation.period_window_invalid"
    OBSERVATION_PERIOD_INCOMPLETE = "r6_monitoring.observation.period_incomplete"
    OBSERVATION_PERIOD_COVERAGE_INCOMPLETE = "r6_monitoring.observation.period_coverage_incomplete"
    OBSERVATION_PERIOD_OVERLAP = "r6_monitoring.observation.period_overlap"
    PERIOD_CALENDAR_MISMATCH = "r6_monitoring.observation.period_calendar_mismatch"
    PERIOD_CALENDAR_MISSING = "r6_monitoring.period_calendar.missing"
    PERIOD_CALENDAR_BINDING_MISMATCH = "r6_monitoring.period_calendar.binding_mismatch"
    PERIOD_CALENDAR_HASH_MISMATCH = "r6_monitoring.period_calendar.hash_mismatch"
    PERIOD_CALENDAR_FROM_FUTURE = "r6_monitoring.period_calendar.from_future"
    PERIOD_CALENDAR_INACTIVE = "r6_monitoring.period_calendar.inactive"
    PERIOD_CALENDAR_HORIZON_INSUFFICIENT = "r6_monitoring.period_calendar.horizon_insufficient"
    OBSERVATION_PERIOD_NOT_IN_CALENDAR = "r6_monitoring.observation.period_not_in_calendar"
    OBSERVATION_BINDING_MISMATCH = "r6_monitoring.observation.binding_mismatch"
    OBSERVATION_OWNER_MISMATCH = "r6_monitoring.observation.owner_mismatch"
    PIT_MANIFEST_MISMATCH = "r6_monitoring.observation.pit_manifest_mismatch"
    EVIDENCE_REF_MISMATCH = "r6_monitoring.observation.evidence_ref_mismatch"
    OBSERVATION_HASH_MISMATCH = "r6_monitoring.observation.hash_mismatch"
    OBSERVATION_FROM_FUTURE = "r6_monitoring.observation.from_future"
    OBSERVATION_STALE = "r6_monitoring.observation.stale"
    OBSERVATION_COUNT_INSUFFICIENT = "r6_monitoring.observation.count_insufficient"
    METRIC_MISSING = "r6_monitoring.metric.missing"
    METRIC_DUPLICATE = "r6_monitoring.metric.duplicate"
    METRIC_UNIT_MISSING = "r6_monitoring.metric.unit_missing"
    METRIC_UNIT_MISMATCH = "r6_monitoring.metric.unit_mismatch"
    LABEL_PROTOCOL_MISMATCH = "r6_monitoring.label.protocol_mismatch"


@dataclass(frozen=True)
class R6MonitoringPeriodEntry:
    """One exact canonical member of a versioned monitoring calendar."""

    period_id: str
    period_start: datetime
    period_end: datetime

    def __post_init__(self) -> None:
        _require_hash(self.period_id, "R6MonitoringPeriodEntry.period_id")
        _require_aware(self.period_start, "R6MonitoringPeriodEntry.period_start")
        _require_aware(self.period_end, "R6MonitoringPeriodEntry.period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R6 monitoring calendar period must be non-empty")


@dataclass(frozen=True)
class R6MonitoringPeriodCalendar:
    """Owner-recorded canonical period membership manifest."""

    source_owner: str
    calendar_id: str
    calendar_version: str
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    entries: tuple[R6MonitoringPeriodEntry, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.source_owner, "R6MonitoringPeriodCalendar.source_owner")
        _require_token(self.calendar_id, "R6MonitoringPeriodCalendar.calendar_id")
        _require_token(
            self.calendar_version,
            "R6MonitoringPeriodCalendar.calendar_version",
        )
        _require_aware(self.recorded_at, "R6MonitoringPeriodCalendar.recorded_at")
        _require_aware(self.valid_from, "R6MonitoringPeriodCalendar.valid_from")
        _require_aware(self.valid_until, "R6MonitoringPeriodCalendar.valid_until")
        if not self.recorded_at <= self.valid_from < self.valid_until:
            raise ValueError("R6 monitoring period calendar clocks are invalid")
        if not self.entries:
            raise ValueError("R6 monitoring period calendar entries are required")
        ordered = tuple(
            sorted(
                self.entries,
                key=lambda item: (item.period_start, item.period_end, item.period_id),
            )
        )
        period_ids = tuple(item.period_id for item in ordered)
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("R6 monitoring period calendar IDs must be unique")
        for entry in ordered:
            expected_period_id = derive_r6_monitoring_period_id(
                period_calendar_id=self.calendar_id,
                period_calendar_version=self.calendar_version,
                period_start=entry.period_start,
                period_end=entry.period_end,
            )
            if entry.period_id.lower() != expected_period_id.lower():
                raise ValueError("R6 monitoring calendar period identity is not canonical")
            if not self.valid_from <= entry.period_start < entry.period_end <= self.valid_until:
                raise ValueError("R6 monitoring calendar period lies outside validity")
        if any(
            current.period_start < previous.period_end
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("R6 monitoring period calendar entries cannot overlap")
        if any(
            current.period_start != previous.period_end
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("R6 monitoring period calendar entries must be contiguous")
        if ordered[0].period_start != self.valid_from or ordered[-1].period_end != self.valid_until:
            raise ValueError("R6 monitoring period calendar must cover its full validity window")
        object.__setattr__(self, "content_hash", _monitoring_period_calendar_hash(self))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this owner calendar is known and valid at ``as_of``."""

        _require_aware(as_of, "R6MonitoringPeriodCalendar.as_of")
        return self.recorded_at <= as_of and self.valid_from <= as_of < self.valid_until


def _monitoring_period_calendar_hash(calendar: R6MonitoringPeriodCalendar) -> str:
    return _hash_payload(
        {
            "schema": "r6-monitoring-period-calendar.v1",
            "source_owner": calendar.source_owner,
            "calendar_id": calendar.calendar_id,
            "calendar_version": calendar.calendar_version,
            "recorded_at": _utc_text(calendar.recorded_at),
            "valid_from": _utc_text(calendar.valid_from),
            "valid_until": _utc_text(calendar.valid_until),
            "entries": [
                {
                    "period_id": item.period_id.lower(),
                    "period_start": _utc_text(item.period_start),
                    "period_end": _utc_text(item.period_end),
                }
                for item in sorted(
                    calendar.entries,
                    key=lambda value: (
                        value.period_start,
                        value.period_end,
                        value.period_id,
                    ),
                )
            ],
        }
    )


def r6_monitoring_period_calendar_hash(calendar: R6MonitoringPeriodCalendar) -> str:
    """Recompute the canonical monitoring-calendar content seal."""

    return _monitoring_period_calendar_hash(calendar)


@dataclass(frozen=True)
class R6MonitoringThreshold:
    """One injected metric threshold and its consecutive-review rule."""

    metric_key: R6MonitoringMetricKey
    unit: str
    direction: R6MonitoringThresholdDirection
    breach_threshold: Decimal
    retirement_review_consecutive_breaches: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R6MonitoringMetricKey):
            raise ValueError("R6 monitoring threshold metric_key is invalid")
        _require_token(self.unit, "R6MonitoringThreshold.unit", maximum=48)
        if not isinstance(self.direction, R6MonitoringThresholdDirection):
            raise ValueError("R6 monitoring threshold direction is invalid")
        _require_metric_domain(
            self.metric_key,
            self.breach_threshold,
            "R6MonitoringThreshold.breach_threshold",
        )
        if (
            isinstance(self.retirement_review_consecutive_breaches, bool)
            or self.retirement_review_consecutive_breaches < 1
        ):
            raise ValueError("retirement review breach count must be positive")

    def is_breached(self, value: Decimal) -> bool:
        """Return whether one raw metric violates this exact threshold."""

        _require_finite(value, "R6MonitoringThreshold.value")
        if self.direction is R6MonitoringThresholdDirection.AT_LEAST:
            return value < self.breach_threshold
        return value > self.breach_threshold


@dataclass(frozen=True)
class R6MonitoringPolicy:
    """Versioned Research monitoring policy with no code-default thresholds."""

    policy_id: str
    policy_version: str
    qualification_ref: R6QualificationRef
    thresholds: tuple[R6MonitoringThreshold, ...]
    minimum_observation_count: int
    maximum_observation_age_seconds: int
    label_protocol_version: str
    expected_label_set_hash: str
    expected_source_owner: str
    expected_pit_manifest_id: str
    expected_pit_manifest_hash: str
    expected_period_calendar_owner: str
    expected_period_calendar_id: str
    expected_period_calendar_version: str
    expected_period_calendar_hash: str
    expected_evidence_ref_prefix: str
    recorded_at: datetime
    active_from: datetime
    active_until: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R6MonitoringPolicy.policy_id")
        _require_token(self.policy_version, "R6MonitoringPolicy.policy_version")
        _require_hash(
            self.qualification_ref.assessment_hash,
            "R6MonitoringPolicy.qualification_ref.assessment_hash",
        )
        keys = tuple(item.metric_key for item in self.thresholds)
        if len(keys) != len(set(keys)):
            raise ValueError("R6 monitoring policy metric thresholds must be unique")
        if frozenset(keys) != REQUIRED_R6_MONITORING_METRICS:
            raise ValueError("R6 monitoring policy must inject every required threshold")
        if isinstance(self.minimum_observation_count, bool) or self.minimum_observation_count < 1:
            raise ValueError("minimum_observation_count must be positive")
        if (
            isinstance(self.maximum_observation_age_seconds, bool)
            or self.maximum_observation_age_seconds < 1
        ):
            raise ValueError("maximum_observation_age_seconds must be positive")
        _require_token(
            self.label_protocol_version,
            "R6MonitoringPolicy.label_protocol_version",
        )
        _require_hash(
            self.expected_label_set_hash,
            "R6MonitoringPolicy.expected_label_set_hash",
        )
        _require_token(
            self.expected_source_owner,
            "R6MonitoringPolicy.expected_source_owner",
        )
        _require_token(
            self.expected_pit_manifest_id,
            "R6MonitoringPolicy.expected_pit_manifest_id",
        )
        _require_hash(
            self.expected_pit_manifest_hash,
            "R6MonitoringPolicy.expected_pit_manifest_hash",
        )
        _require_token(
            self.expected_period_calendar_owner,
            "R6MonitoringPolicy.expected_period_calendar_owner",
        )
        _require_token(
            self.expected_period_calendar_id,
            "R6MonitoringPolicy.expected_period_calendar_id",
        )
        _require_token(
            self.expected_period_calendar_version,
            "R6MonitoringPolicy.expected_period_calendar_version",
        )
        _require_hash(
            self.expected_period_calendar_hash,
            "R6MonitoringPolicy.expected_period_calendar_hash",
        )
        _require_text(
            self.expected_evidence_ref_prefix,
            "R6MonitoringPolicy.expected_evidence_ref_prefix",
        )
        _require_aware(self.recorded_at, "R6MonitoringPolicy.recorded_at")
        _require_aware(self.active_from, "R6MonitoringPolicy.active_from")
        _require_aware(self.active_until, "R6MonitoringPolicy.active_until")
        if not self.recorded_at <= self.active_from < self.active_until:
            raise ValueError("R6 monitoring policy knowledge/active clocks are invalid")
        object.__setattr__(self, "content_hash", _monitoring_policy_hash(self))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact policy is active at ``as_of``."""

        _require_aware(as_of, "R6MonitoringPolicy.as_of")
        return self.active_from <= as_of < self.active_until


def _monitoring_policy_hash(policy: R6MonitoringPolicy) -> str:
    return _hash_payload(
        {
            "schema": "r6-monitoring-policy.v2",
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "qualification_ref": {
                "assessment_id": policy.qualification_ref.assessment_id,
                "assessment_hash": policy.qualification_ref.assessment_hash.lower(),
            },
            "thresholds": [
                {
                    "metric_key": item.metric_key.value,
                    "unit": item.unit,
                    "direction": item.direction.value,
                    "breach_threshold": _decimal_text(item.breach_threshold),
                    "retirement_review_consecutive_breaches": (
                        item.retirement_review_consecutive_breaches
                    ),
                }
                for item in sorted(policy.thresholds, key=lambda value: value.metric_key.value)
            ],
            "minimum_observation_count": policy.minimum_observation_count,
            "maximum_observation_age_seconds": policy.maximum_observation_age_seconds,
            "label_protocol_version": policy.label_protocol_version,
            "expected_label_set_hash": policy.expected_label_set_hash.lower(),
            "expected_source_owner": policy.expected_source_owner,
            "expected_pit_manifest_id": policy.expected_pit_manifest_id,
            "expected_pit_manifest_hash": policy.expected_pit_manifest_hash.lower(),
            "expected_period_calendar_owner": policy.expected_period_calendar_owner,
            "expected_period_calendar_id": policy.expected_period_calendar_id,
            "expected_period_calendar_version": policy.expected_period_calendar_version,
            "expected_period_calendar_hash": policy.expected_period_calendar_hash.lower(),
            "expected_evidence_ref_prefix": policy.expected_evidence_ref_prefix,
            "recorded_at": _utc_text(policy.recorded_at),
            "active_from": _utc_text(policy.active_from),
            "active_until": _utc_text(policy.active_until),
        }
    )


def r6_monitoring_policy_hash(policy: R6MonitoringPolicy) -> str:
    """Recompute the canonical monitoring-policy content seal."""

    return _monitoring_policy_hash(policy)


@dataclass(frozen=True)
class R6MonitoringMetricObservation:
    """One raw owner value; incompleteness is assessed rather than defaulted."""

    metric_key: R6MonitoringMetricKey
    unit: str
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R6MonitoringMetricKey):
            raise ValueError("R6 monitoring observation metric_key is invalid")
        if not isinstance(self.unit, str) or len(self.unit) > 48:
            raise ValueError("R6 monitoring observation unit is invalid")
        _require_metric_domain(
            self.metric_key,
            self.value,
            "R6MonitoringMetricObservation.value",
        )


@dataclass(frozen=True)
class R6MonitoringObservation:
    """Content-sealed raw monitoring facts from one canonical owner window."""

    observation_id: str
    observation_version: str
    observation_period_id: str
    period_calendar_id: str
    period_calendar_version: str
    period_calendar_hash: str
    period_start: datetime
    period_end: datetime
    qualification_ref: R6QualificationRef
    policy_id: str
    policy_version: str
    policy_hash: str
    source_owner: str
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    evidence_ref: str
    label_protocol_version: str
    observed_label_set_hash: str
    metrics: tuple[R6MonitoringMetricObservation, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
            "period_calendar_id",
            "period_calendar_version",
            "policy_id",
            "policy_version",
            "source_owner",
            "pit_manifest_id",
            "label_protocol_version",
        ):
            _require_token(getattr(self, field_name), f"R6MonitoringObservation.{field_name}")
        _require_hash(
            self.observation_period_id,
            "R6MonitoringObservation.observation_period_id",
        )
        _require_hash(
            self.period_calendar_hash,
            "R6MonitoringObservation.period_calendar_hash",
        )
        _require_hash(self.policy_hash, "R6MonitoringObservation.policy_hash")
        _require_hash(
            self.qualification_ref.assessment_hash,
            "R6MonitoringObservation.qualification_ref.assessment_hash",
        )
        _require_hash(self.pit_manifest_hash, "R6MonitoringObservation.pit_manifest_hash")
        _require_hash(
            self.observed_label_set_hash,
            "R6MonitoringObservation.observed_label_set_hash",
        )
        _require_text(self.evidence_ref, "R6MonitoringObservation.evidence_ref")
        _require_aware(self.observed_at, "R6MonitoringObservation.observed_at")
        _require_aware(self.period_start, "R6MonitoringObservation.period_start")
        _require_aware(self.period_end, "R6MonitoringObservation.period_end")
        _require_aware(self.available_at, "R6MonitoringObservation.available_at")
        _require_aware(self.recorded_at, "R6MonitoringObservation.recorded_at")
        _require_aware(self.valid_until, "R6MonitoringObservation.valid_until")
        if not self.observed_at <= self.available_at <= self.recorded_at < self.valid_until:
            raise ValueError("R6 monitoring observation evidence clocks are invalid")
        if not self.period_start <= self.observed_at < self.period_end:
            raise ValueError("R6 monitoring observed_at must fall within its period window")
        expected_period_id = derive_r6_monitoring_period_id(
            period_calendar_id=self.period_calendar_id,
            period_calendar_version=self.period_calendar_version,
            period_start=self.period_start,
            period_end=self.period_end,
        )
        if self.observation_period_id.lower() != expected_period_id.lower():
            raise ValueError("R6 monitoring observation period identity is not canonical")
        if not (
            self.research_only
            and self.must_not_use_for_decision
            and self.must_not_replace_regime
            and self.must_not_publish_current
            and self.must_not_execute
        ):
            raise ValueError("R6 monitoring facts cannot authorize production behavior")
        object.__setattr__(self, "content_hash", _monitoring_observation_hash(self))


def _monitoring_observation_hash(observation: R6MonitoringObservation) -> str:
    return _hash_payload(
        {
            "schema": "r6-monitoring-observation.v1",
            "observation_id": observation.observation_id,
            "observation_version": observation.observation_version,
            "observation_period_id": observation.observation_period_id,
            "period_calendar_id": observation.period_calendar_id,
            "period_calendar_version": observation.period_calendar_version,
            "period_calendar_hash": observation.period_calendar_hash.lower(),
            "period_start": _utc_text(observation.period_start),
            "period_end": _utc_text(observation.period_end),
            "qualification_ref": {
                "assessment_id": observation.qualification_ref.assessment_id,
                "assessment_hash": observation.qualification_ref.assessment_hash.lower(),
            },
            "policy_id": observation.policy_id,
            "policy_version": observation.policy_version,
            "policy_hash": observation.policy_hash.lower(),
            "source_owner": observation.source_owner,
            "observed_at": _utc_text(observation.observed_at),
            "available_at": _utc_text(observation.available_at),
            "recorded_at": _utc_text(observation.recorded_at),
            "valid_until": _utc_text(observation.valid_until),
            "pit_manifest_id": observation.pit_manifest_id,
            "pit_manifest_hash": observation.pit_manifest_hash.lower(),
            "evidence_ref": observation.evidence_ref,
            "label_protocol_version": observation.label_protocol_version,
            "observed_label_set_hash": observation.observed_label_set_hash.lower(),
            "metrics": [
                {
                    "metric_key": item.metric_key.value,
                    "unit": item.unit,
                    "value": _decimal_text(item.value),
                }
                for item in sorted(
                    observation.metrics,
                    key=lambda value: value.metric_key.value,
                )
            ],
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_replace_regime": True,
            "must_not_publish_current": True,
            "must_not_execute": True,
        }
    )


def r6_monitoring_observation_hash(observation: R6MonitoringObservation) -> str:
    """Recompute one canonical raw-observation content seal."""

    return _monitoring_observation_hash(observation)


@dataclass(frozen=True)
class R6MonitoringMetricResult:
    """Recomputed latest threshold state and trailing breach count."""

    metric_key: R6MonitoringMetricKey
    unit: str
    latest_value: Decimal
    breach_threshold: Decimal
    direction: R6MonitoringThresholdDirection
    latest_breached: bool
    trailing_consecutive_breaches: int
    retirement_review_consecutive_breaches: int


@dataclass(frozen=True)
class R6MonitoringAssessment:
    """Research-only assessment; review does not mutate lifecycle state."""

    qualification_ref: R6QualificationRef
    requested_policy_id: str
    requested_policy_version: str
    expected_policy_hash: str
    qualification_content_hash: str | None
    policy_hash: str | None
    evaluated_at: datetime
    status: R6MonitoringAssessmentStatus
    observation_hashes: tuple[str, ...]
    metric_results: tuple[R6MonitoringMetricResult, ...]
    blockers: tuple[R6MonitoringBlockerCode, ...]
    label_drift_detected: bool
    retirement_review_required: bool
    automatic_retirement: bool = False
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.requested_policy_id, "R6MonitoringAssessment.requested_policy_id")
        _require_token(
            self.requested_policy_version,
            "R6MonitoringAssessment.requested_policy_version",
        )
        _require_hash(
            self.expected_policy_hash,
            "R6MonitoringAssessment.expected_policy_hash",
        )
        _require_hash(
            self.qualification_ref.assessment_hash,
            "R6MonitoringAssessment.qualification_ref.assessment_hash",
        )
        if self.qualification_content_hash is not None:
            _require_hash(
                self.qualification_content_hash,
                "R6MonitoringAssessment.qualification_content_hash",
            )
        if self.policy_hash is not None:
            _require_hash(self.policy_hash, "R6MonitoringAssessment.policy_hash")
        _require_aware(self.evaluated_at, "R6MonitoringAssessment.evaluated_at")
        if len(self.blockers) != len(set(self.blockers)):
            raise ValueError("R6 monitoring blockers must be unique")
        if len(self.observation_hashes) != len(set(self.observation_hashes)):
            raise ValueError("R6 monitoring observation hashes must be unique")
        for value in self.observation_hashes:
            _require_hash(value, "R6MonitoringAssessment.observation_hash")
        if self.status is R6MonitoringAssessmentStatus.BLOCKED:
            if not self.blockers or self.metric_results or self.retirement_review_required:
                raise ValueError("blocked R6 monitoring assessment shape is invalid")
        elif self.blockers:
            raise ValueError("non-blocked R6 monitoring assessment cannot contain blockers")
        if self.status is R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED:
            if not self.retirement_review_required:
                raise ValueError("retirement-review status requires the review flag")
        elif self.retirement_review_required:
            raise ValueError("only retirement-review status may request review")
        if self.automatic_retirement:
            raise ValueError("R6 monitoring cannot automatically retire a qualification")
        if not (
            self.research_only
            and self.must_not_use_for_decision
            and self.must_not_replace_regime
            and self.must_not_publish_current
            and self.must_not_execute
        ):
            raise ValueError("R6 monitoring assessment cannot authorize production behavior")
        object.__setattr__(self, "content_hash", _monitoring_assessment_hash(self))


def _monitoring_assessment_hash(assessment: R6MonitoringAssessment) -> str:
    return _hash_payload(
        {
            "schema": "r6-monitoring-assessment.v1",
            "qualification_ref": {
                "assessment_id": assessment.qualification_ref.assessment_id,
                "assessment_hash": assessment.qualification_ref.assessment_hash.lower(),
            },
            "requested_policy_id": assessment.requested_policy_id,
            "requested_policy_version": assessment.requested_policy_version,
            "expected_policy_hash": assessment.expected_policy_hash.lower(),
            "qualification_content_hash": assessment.qualification_content_hash,
            "policy_hash": assessment.policy_hash,
            "evaluated_at": _utc_text(assessment.evaluated_at),
            "status": assessment.status.value,
            "observation_hashes": list(assessment.observation_hashes),
            "metric_results": [
                {
                    "metric_key": item.metric_key.value,
                    "unit": item.unit,
                    "latest_value": _decimal_text(item.latest_value),
                    "breach_threshold": _decimal_text(item.breach_threshold),
                    "direction": item.direction.value,
                    "latest_breached": item.latest_breached,
                    "trailing_consecutive_breaches": item.trailing_consecutive_breaches,
                    "retirement_review_consecutive_breaches": (
                        item.retirement_review_consecutive_breaches
                    ),
                }
                for item in assessment.metric_results
            ],
            "blockers": [item.value for item in assessment.blockers],
            "label_drift_detected": assessment.label_drift_detected,
            "retirement_review_required": assessment.retirement_review_required,
            "automatic_retirement": False,
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_replace_regime": True,
            "must_not_publish_current": True,
            "must_not_execute": True,
        }
    )


def evaluate_r6_monitoring(
    *,
    qualification_ref: R6QualificationRef,
    qualification_content_hash: str | None,
    qualification_assessed_at: datetime | None,
    qualification_known_at: datetime | None,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    policy: R6MonitoringPolicy | None,
    period_calendar: R6MonitoringPeriodCalendar | None,
    observations: tuple[R6MonitoringObservation, ...],
    evaluated_at: datetime,
) -> R6MonitoringAssessment:
    """Recompute monitoring state from exact policy and canonical raw facts."""

    _require_token(requested_policy_id, "requested_policy_id")
    _require_token(requested_policy_version, "requested_policy_version")
    _require_hash(expected_policy_hash, "expected_policy_hash")
    _require_hash(
        qualification_ref.assessment_hash,
        "qualification_ref.assessment_hash",
    )
    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[R6MonitoringBlockerCode] = []
    qualification_clocks_valid = False
    if qualification_content_hash is None:
        blockers.append(R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_MISSING)
    elif not _hashes_equal(
        qualification_content_hash,
        qualification_ref.assessment_hash,
    ):
        blockers.append(R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID)
    elif qualification_assessed_at is None or qualification_known_at is None:
        blockers.append(R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID)
    else:
        try:
            _require_aware(qualification_assessed_at, "qualification_assessed_at")
            _require_aware(qualification_known_at, "qualification_known_at")
        except (AttributeError, TypeError, ValueError):
            blockers.append(R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID)
        else:
            if (
                qualification_assessed_at > qualification_known_at
                or qualification_known_at > evaluated_at
            ):
                blockers.append(R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID)
            else:
                qualification_clocks_valid = True
    if policy is None:
        blockers.append(R6MonitoringBlockerCode.POLICY_MISSING)
    else:
        try:
            recomputed_policy_hash = _monitoring_policy_hash(policy)
        except (AttributeError, TypeError, ValueError):
            recomputed_policy_hash = None
        if (
            policy.policy_id != requested_policy_id
            or policy.policy_version != requested_policy_version
            or policy.qualification_ref != qualification_ref
        ):
            blockers.append(R6MonitoringBlockerCode.POLICY_BINDING_MISMATCH)
        if not _hashes_equal(policy.content_hash, recomputed_policy_hash) or not _hashes_equal(
            recomputed_policy_hash, expected_policy_hash
        ):
            blockers.append(R6MonitoringBlockerCode.POLICY_HASH_MISMATCH)
        if policy.recorded_at > evaluated_at:
            blockers.append(R6MonitoringBlockerCode.POLICY_FROM_FUTURE)
        if (
            qualification_clocks_valid
            and qualification_assessed_at is not None
            and qualification_known_at is not None
            and policy.recorded_at < max(qualification_assessed_at, qualification_known_at)
        ):
            blockers.append(R6MonitoringBlockerCode.POLICY_QUALIFICATION_CAUSALITY_INVALID)
        if not policy.is_active_at(evaluated_at):
            blockers.append(R6MonitoringBlockerCode.POLICY_INACTIVE)
    if period_calendar is None:
        blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_MISSING)
    elif policy is not None:
        try:
            recomputed_calendar_hash = _monitoring_period_calendar_hash(period_calendar)
        except (AttributeError, TypeError, ValueError):
            recomputed_calendar_hash = None
        if (
            period_calendar.source_owner != policy.expected_period_calendar_owner
            or period_calendar.calendar_id != policy.expected_period_calendar_id
            or period_calendar.calendar_version != policy.expected_period_calendar_version
        ):
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_BINDING_MISMATCH)
        if not _hashes_equal(
            period_calendar.content_hash, recomputed_calendar_hash
        ) or not _hashes_equal(
            recomputed_calendar_hash,
            policy.expected_period_calendar_hash,
        ):
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH)
        if period_calendar.recorded_at > evaluated_at:
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_FROM_FUTURE)
        if not period_calendar.is_active_at(evaluated_at):
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_INACTIVE)
        if (
            period_calendar.valid_from > policy.active_from
            or period_calendar.valid_until < policy.active_until
        ):
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_HORIZON_INSUFFICIENT)
    if not observations:
        blockers.append(R6MonitoringBlockerCode.OBSERVATIONS_MISSING)
    if policy is None or period_calendar is None or blockers:
        return _blocked_monitoring_assessment(
            qualification_ref=qualification_ref,
            requested_policy_id=requested_policy_id,
            requested_policy_version=requested_policy_version,
            expected_policy_hash=expected_policy_hash,
            qualification_content_hash=qualification_content_hash,
            policy_hash=(
                policy.content_hash
                if policy is not None and _is_hash(policy.content_hash)
                else None
            ),
            evaluated_at=evaluated_at,
            observations=observations,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.period_start,
                item.period_end,
                item.observation_period_id,
                item.recorded_at,
                item.content_hash,
            ),
        )
    )
    if observations != ordered:
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_ORDER_INVALID)
    identities = tuple((item.observation_id, item.observation_version) for item in ordered)
    if len(identities) != len(set(identities)):
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_IDENTITY_DUPLICATE)
    periods = tuple(item.observation_period_id for item in ordered)
    if len(periods) != len(set(periods)):
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_DUPLICATE)
    if any(
        current.period_start < previous.period_end
        for previous, current in zip(ordered, ordered[1:], strict=False)
    ):
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_OVERLAP)
    if len(ordered) < policy.minimum_observation_count:
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_COUNT_INSUFFICIENT)
    threshold_by_key = {item.metric_key: item for item in policy.thresholds}
    ordered_calendar_entries = tuple(
        sorted(
            period_calendar.entries,
            key=lambda item: (item.period_start, item.period_end, item.period_id),
        )
    )
    calendar_entry_by_id = {item.period_id: item for item in ordered_calendar_entries}
    completed_calendar_entries = tuple(
        item for item in ordered_calendar_entries if item.period_end <= evaluated_at
    )
    monitoring_floor = evaluated_at - timedelta(seconds=policy.maximum_observation_age_seconds)
    selected_calendar_entries = tuple(
        item for item in completed_calendar_entries if item.period_end > monitoring_floor
    )
    selected_period_ids = tuple(item.period_id for item in selected_calendar_entries)
    if (
        len(selected_calendar_entries) < policy.minimum_observation_count
        or periods != selected_period_ids
    ):
        blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_COVERAGE_INCOMPLETE)
    values_by_observation: list[dict[R6MonitoringMetricKey, Decimal]] = []
    label_drift = False
    for observation in ordered:
        try:
            recomputed_observation_hash = _monitoring_observation_hash(observation)
        except (AttributeError, TypeError, ValueError):
            recomputed_observation_hash = None
        if not _hashes_equal(
            observation.content_hash,
            recomputed_observation_hash,
        ):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH)
        try:
            derived_period_id = derive_r6_monitoring_period_id(
                period_calendar_id=observation.period_calendar_id,
                period_calendar_version=observation.period_calendar_version,
                period_start=observation.period_start,
                period_end=observation.period_end,
            )
        except (TypeError, ValueError):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_WINDOW_INVALID)
        else:
            if not _hashes_equal(
                observation.observation_period_id,
                derived_period_id,
            ):
                blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_ID_MISMATCH)
        if not observation.period_start <= observation.observed_at < observation.period_end:
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_WINDOW_INVALID)
        if observation.period_end > evaluated_at:
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_INCOMPLETE)
        if (
            observation.period_calendar_id != policy.expected_period_calendar_id
            or observation.period_calendar_version != policy.expected_period_calendar_version
            or not _hashes_equal(
                observation.period_calendar_hash,
                policy.expected_period_calendar_hash,
            )
        ):
            blockers.append(R6MonitoringBlockerCode.PERIOD_CALENDAR_MISMATCH)
        calendar_entry = calendar_entry_by_id.get(observation.observation_period_id)
        if (
            calendar_entry is None
            or calendar_entry.period_start != observation.period_start
            or calendar_entry.period_end != observation.period_end
        ):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_PERIOD_NOT_IN_CALENDAR)
        if (
            observation.qualification_ref != qualification_ref
            or observation.policy_id != policy.policy_id
            or observation.policy_version != policy.policy_version
            or not _hashes_equal(observation.policy_hash, policy.content_hash)
        ):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_BINDING_MISMATCH)
        if observation.source_owner != policy.expected_source_owner:
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_OWNER_MISMATCH)
        if observation.pit_manifest_id != policy.expected_pit_manifest_id or not _hashes_equal(
            observation.pit_manifest_hash,
            policy.expected_pit_manifest_hash,
        ):
            blockers.append(R6MonitoringBlockerCode.PIT_MANIFEST_MISMATCH)
        if not observation.evidence_ref.startswith(policy.expected_evidence_ref_prefix):
            blockers.append(R6MonitoringBlockerCode.EVIDENCE_REF_MISMATCH)
        if (
            observation.observed_at > evaluated_at
            or observation.available_at > evaluated_at
            or observation.recorded_at > evaluated_at
        ):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_FROM_FUTURE)
        age_seconds = (evaluated_at - observation.observed_at).total_seconds()
        if (
            evaluated_at >= observation.valid_until
            or age_seconds > policy.maximum_observation_age_seconds
        ):
            blockers.append(R6MonitoringBlockerCode.OBSERVATION_STALE)
        if observation.label_protocol_version != policy.label_protocol_version:
            blockers.append(R6MonitoringBlockerCode.LABEL_PROTOCOL_MISMATCH)
        elif not _hashes_equal(
            observation.observed_label_set_hash,
            policy.expected_label_set_hash,
        ):
            label_drift = True
        metric_keys = tuple(item.metric_key for item in observation.metrics)
        if len(metric_keys) != len(set(metric_keys)):
            blockers.append(R6MonitoringBlockerCode.METRIC_DUPLICATE)
        if frozenset(metric_keys) != REQUIRED_R6_MONITORING_METRICS:
            blockers.append(R6MonitoringBlockerCode.METRIC_MISSING)
        values: dict[R6MonitoringMetricKey, Decimal] = {}
        for metric in observation.metrics:
            if not metric.unit.strip():
                blockers.append(R6MonitoringBlockerCode.METRIC_UNIT_MISSING)
            elif metric.unit != threshold_by_key[metric.metric_key].unit:
                blockers.append(R6MonitoringBlockerCode.METRIC_UNIT_MISMATCH)
            values.setdefault(metric.metric_key, metric.value)
        values_by_observation.append(values)
    if blockers:
        return _blocked_monitoring_assessment(
            qualification_ref=qualification_ref,
            requested_policy_id=requested_policy_id,
            requested_policy_version=requested_policy_version,
            expected_policy_hash=expected_policy_hash,
            qualification_content_hash=qualification_content_hash,
            policy_hash=(policy.content_hash if _is_hash(policy.content_hash) else None),
            evaluated_at=evaluated_at,
            observations=ordered,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    results: list[R6MonitoringMetricResult] = []
    review_required = label_drift
    any_latest_breach = False
    for metric_key in sorted(REQUIRED_R6_MONITORING_METRICS, key=lambda item: item.value):
        threshold = threshold_by_key[metric_key]
        metric_history = tuple(item[metric_key] for item in values_by_observation)
        breached = tuple(threshold.is_breached(value) for value in metric_history)
        trailing = 0
        for item in reversed(breached):
            if not item:
                break
            trailing += 1
        latest_breached = breached[-1]
        any_latest_breach = any_latest_breach or latest_breached
        if latest_breached and trailing >= threshold.retirement_review_consecutive_breaches:
            review_required = True
        results.append(
            R6MonitoringMetricResult(
                metric_key=metric_key,
                unit=threshold.unit,
                latest_value=metric_history[-1],
                breach_threshold=threshold.breach_threshold,
                direction=threshold.direction,
                latest_breached=latest_breached,
                trailing_consecutive_breaches=trailing,
                retirement_review_consecutive_breaches=(
                    threshold.retirement_review_consecutive_breaches
                ),
            )
        )
    status = (
        R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
        if review_required
        else (
            R6MonitoringAssessmentStatus.BREACHED
            if any_latest_breach
            else R6MonitoringAssessmentStatus.HEALTHY
        )
    )
    return R6MonitoringAssessment(
        qualification_ref=qualification_ref,
        requested_policy_id=requested_policy_id,
        requested_policy_version=requested_policy_version,
        expected_policy_hash=expected_policy_hash,
        qualification_content_hash=qualification_content_hash,
        policy_hash=policy.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        observation_hashes=tuple(item.content_hash for item in ordered),
        metric_results=tuple(results),
        blockers=(),
        label_drift_detected=label_drift,
        retirement_review_required=review_required,
    )


def _blocked_monitoring_assessment(
    *,
    qualification_ref: R6QualificationRef,
    requested_policy_id: str,
    requested_policy_version: str,
    expected_policy_hash: str,
    qualification_content_hash: str | None,
    policy_hash: str | None,
    evaluated_at: datetime,
    observations: tuple[R6MonitoringObservation, ...],
    blockers: tuple[R6MonitoringBlockerCode, ...],
) -> R6MonitoringAssessment:
    return R6MonitoringAssessment(
        qualification_ref=qualification_ref,
        requested_policy_id=requested_policy_id,
        requested_policy_version=requested_policy_version,
        expected_policy_hash=expected_policy_hash,
        qualification_content_hash=qualification_content_hash,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        status=R6MonitoringAssessmentStatus.BLOCKED,
        observation_hashes=tuple(
            dict.fromkeys(item.content_hash for item in observations if _is_hash(item.content_hash))
        ),
        metric_results=(),
        blockers=blockers,
        label_drift_detected=False,
        retirement_review_required=False,
    )


__all__ = [
    "REQUIRED_R6_MONITORING_METRICS",
    "R6MonitoringAssessment",
    "R6MonitoringAssessmentStatus",
    "R6MonitoringBlockerCode",
    "R6MonitoringMetricKey",
    "R6MonitoringMetricObservation",
    "R6MonitoringMetricResult",
    "R6MonitoringObservation",
    "R6MonitoringPeriodCalendar",
    "R6MonitoringPeriodEntry",
    "R6MonitoringPolicy",
    "R6MonitoringThreshold",
    "R6MonitoringThresholdDirection",
    "derive_r6_monitoring_period_id",
    "evaluate_r6_monitoring",
    "r6_monitoring_observation_hash",
    "r6_monitoring_period_calendar_hash",
    "r6_monitoring_policy_hash",
]
