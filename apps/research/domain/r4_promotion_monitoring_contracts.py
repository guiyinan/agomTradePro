"""Versioned evidence contracts for R4 post-promotion monitoring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from .r4_promotion_decision import R4PromotionDecisionOutcome
from .r4_promotion_lifecycle import R4PromotionDecisionIdentity


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_text(value: object, field_name: str, *, maximum: int = 300) -> None:
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
        _is_hash(left)
        and _is_hash(right)
        and isinstance(left, str)
        and isinstance(right, str)
        and left.lower() == right.lower()
    )


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: object, field_name: str) -> None:
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


def derive_r4_monitoring_period_id(
    *,
    calendar_id: str,
    calendar_version: str,
    period_start: datetime,
    period_end: datetime,
) -> str:
    """Derive one exact calendar-member identity from its canonical window."""

    _require_token(calendar_id, "calendar_id")
    _require_token(calendar_version, "calendar_version")
    _require_aware(period_start, "period_start")
    _require_aware(period_end, "period_end")
    if period_start >= period_end:
        raise ValueError("R4 monitoring period must be non-empty")
    return _hash_payload(
        {
            "schema": "research-r4-monitoring-period.v1",
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "period_start": _utc_text(period_start),
            "period_end": _utc_text(period_end),
        }
    )


class R4MonitoringMetricKey(StrEnum):
    """Required post-promotion performance and drift facts."""

    RELATIVE_NET_RETURN = "relative_net_return"
    RELATIVE_DRAWDOWN_INCREASE = "relative_drawdown_increase"
    RELATIVE_VOLATILITY_INCREASE = "relative_volatility_increase"
    RELATIVE_COST_INCREASE = "relative_cost_increase"
    COVARIANCE_CONDITION_NUMBER = "covariance_condition_number"
    COVARIANCE_COVERAGE_RATIO = "covariance_coverage_ratio"
    RISK_CONTRIBUTION_ERROR = "risk_contribution_error"
    BETA_DRIFT = "beta_drift"
    REGIME_STABILITY_RATIO = "regime_stability_ratio"
    LABEL_DRIFT_RATIO = "label_drift_ratio"
    DATA_DRIFT_RATIO = "data_drift_ratio"


REQUIRED_R4_MONITORING_METRICS: frozenset[R4MonitoringMetricKey] = frozenset(R4MonitoringMetricKey)

_UNIT_INTERVAL_METRICS: frozenset[R4MonitoringMetricKey] = frozenset(
    {
        R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO,
        R4MonitoringMetricKey.REGIME_STABILITY_RATIO,
        R4MonitoringMetricKey.LABEL_DRIFT_RATIO,
        R4MonitoringMetricKey.DATA_DRIFT_RATIO,
    }
)
_NON_NEGATIVE_METRICS: frozenset[R4MonitoringMetricKey] = frozenset(
    {
        R4MonitoringMetricKey.RISK_CONTRIBUTION_ERROR,
        R4MonitoringMetricKey.BETA_DRIFT,
    }
)


def _require_metric_domain(
    metric_key: R4MonitoringMetricKey,
    value: object,
    field_name: str,
) -> None:
    _require_finite(value, field_name)
    assert isinstance(value, Decimal)
    if metric_key in _UNIT_INTERVAL_METRICS and not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{field_name} must be within [0, 1]")
    if metric_key in _NON_NEGATIVE_METRICS and value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    if metric_key is R4MonitoringMetricKey.COVARIANCE_CONDITION_NUMBER and value < 1:
        raise ValueError(f"{field_name} must be at least one")


class R4MonitoringThresholdDirection(StrEnum):
    """Whether a healthy observation stays above or below its threshold."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


_AT_LEAST_METRICS: frozenset[R4MonitoringMetricKey] = frozenset(
    {
        R4MonitoringMetricKey.RELATIVE_NET_RETURN,
        R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO,
        R4MonitoringMetricKey.REGIME_STABILITY_RATIO,
    }
)


def _canonical_threshold_direction(
    metric_key: R4MonitoringMetricKey,
) -> R4MonitoringThresholdDirection:
    return (
        R4MonitoringThresholdDirection.AT_LEAST
        if metric_key in _AT_LEAST_METRICS
        else R4MonitoringThresholdDirection.AT_MOST
    )


@dataclass(frozen=True)
class R4MonitoringPeriodEntry:
    """One exact member of a canonical monitoring calendar."""

    period_id: str
    period_start: datetime
    period_end: datetime

    def __post_init__(self) -> None:
        _require_hash(self.period_id, "R4MonitoringPeriodEntry.period_id")
        _require_aware(self.period_start, "R4MonitoringPeriodEntry.period_start")
        _require_aware(self.period_end, "R4MonitoringPeriodEntry.period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R4 monitoring calendar period must be non-empty")


@dataclass(frozen=True)
class R4MonitoringPeriodCalendar:
    """Owner-recorded manifest defining every admissible monitoring window."""

    source_owner: str
    calendar_id: str
    calendar_version: str
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    entries: tuple[R4MonitoringPeriodEntry, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.source_owner, "R4MonitoringPeriodCalendar.source_owner")
        _require_token(self.calendar_id, "R4MonitoringPeriodCalendar.calendar_id")
        _require_token(self.calendar_version, "R4MonitoringPeriodCalendar.calendar_version")
        _require_aware(self.recorded_at, "R4MonitoringPeriodCalendar.recorded_at")
        _require_aware(self.valid_from, "R4MonitoringPeriodCalendar.valid_from")
        _require_aware(self.valid_until, "R4MonitoringPeriodCalendar.valid_until")
        if not self.recorded_at <= self.valid_from < self.valid_until:
            raise ValueError("R4 monitoring calendar clocks are invalid")
        if not self.entries:
            raise ValueError("R4 monitoring calendar entries are required")
        ordered = tuple(
            sorted(
                self.entries, key=lambda item: (item.period_start, item.period_end, item.period_id)
            )
        )
        period_ids = tuple(item.period_id for item in ordered)
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("R4 monitoring calendar period IDs must be unique")
        for entry in ordered:
            expected = derive_r4_monitoring_period_id(
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                period_start=entry.period_start,
                period_end=entry.period_end,
            )
            if not _hashes_equal(entry.period_id, expected):
                raise ValueError("R4 monitoring calendar period identity is not canonical")
            if not self.valid_from <= entry.period_start < entry.period_end <= self.valid_until:
                raise ValueError("R4 monitoring calendar period lies outside validity")
        if any(
            current.period_start != previous.period_end
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("R4 monitoring calendar periods must be contiguous")
        if ordered[0].period_start != self.valid_from or ordered[-1].period_end != self.valid_until:
            raise ValueError("R4 monitoring calendar must cover its full validity window")
        object.__setattr__(self, "content_hash", r4_monitoring_period_calendar_hash(self))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the calendar is known and covers the cutoff."""

        _require_aware(as_of, "R4MonitoringPeriodCalendar.as_of")
        return self.recorded_at <= as_of and self.valid_from <= as_of < self.valid_until


def r4_monitoring_period_calendar_hash(calendar: R4MonitoringPeriodCalendar) -> str:
    """Recompute the canonical calendar content seal."""

    return _hash_payload(
        {
            "schema": "research-r4-monitoring-period-calendar.v1",
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
                    key=lambda value: (value.period_start, value.period_end, value.period_id),
                )
            ],
        }
    )


@dataclass(frozen=True)
class R4MonitoringThreshold:
    """One injected metric threshold and consecutive-review rule."""

    metric_key: R4MonitoringMetricKey
    unit: str
    direction: R4MonitoringThresholdDirection
    breach_threshold: Decimal
    retirement_review_consecutive_breaches: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R4MonitoringMetricKey):
            raise ValueError("R4 monitoring threshold metric_key is invalid")
        _require_token(self.unit, "R4MonitoringThreshold.unit", maximum=48)
        if not isinstance(self.direction, R4MonitoringThresholdDirection):
            raise ValueError("R4 monitoring threshold direction is invalid")
        if self.direction is not _canonical_threshold_direction(self.metric_key):
            raise ValueError("R4 monitoring threshold violates its canonical direction")
        _require_metric_domain(
            self.metric_key,
            self.breach_threshold,
            "R4MonitoringThreshold.breach_threshold",
        )
        if (
            type(self.retirement_review_consecutive_breaches) is not int
            or self.retirement_review_consecutive_breaches < 1
        ):
            raise ValueError("R4 monitoring consecutive breach count must be positive")

    def is_breached(self, value: Decimal) -> bool:
        """Return whether a raw metric violates this exact policy threshold."""

        _require_metric_domain(self.metric_key, value, "R4MonitoringThreshold.value")
        if self.direction is R4MonitoringThresholdDirection.AT_LEAST:
            return value < self.breach_threshold
        return value > self.breach_threshold


def _validated_threshold_copy(
    threshold: R4MonitoringThreshold,
) -> R4MonitoringThreshold:
    if type(threshold) is not R4MonitoringThreshold:
        raise ValueError("R4 monitoring policy threshold type is invalid")
    rebuilt = R4MonitoringThreshold(
        metric_key=threshold.metric_key,
        unit=threshold.unit,
        direction=threshold.direction,
        breach_threshold=threshold.breach_threshold,
        retirement_review_consecutive_breaches=(threshold.retirement_review_consecutive_breaches),
    )
    if rebuilt != threshold:
        raise ValueError("R4 monitoring policy threshold validation changed its value")
    return rebuilt


@dataclass(frozen=True)
class R4MonitoringPolicy:
    """Content-addressed post-promotion policy with no default thresholds."""

    policy_id: str
    policy_version: str
    active_decision: R4PromotionDecisionIdentity
    thresholds: tuple[R4MonitoringThreshold, ...]
    minimum_observation_count: int
    maximum_observation_age_seconds: int
    expected_source_owner: str
    expected_pit_manifest_id: str
    expected_pit_manifest_hash: str
    expected_label_protocol_version: str
    expected_label_set_hash: str
    expected_data_schema_hash: str
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
        _require_token(self.policy_id, "R4MonitoringPolicy.policy_id")
        _require_token(self.policy_version, "R4MonitoringPolicy.policy_version")
        if not isinstance(self.thresholds, tuple):
            raise ValueError("R4 monitoring policy thresholds must be a tuple")
        validated_thresholds = tuple(_validated_threshold_copy(item) for item in self.thresholds)
        if validated_thresholds != self.thresholds:
            raise ValueError("R4 monitoring policy thresholds failed validation")
        keys = tuple(item.metric_key for item in validated_thresholds)
        if len(keys) != len(set(keys)) or frozenset(keys) != REQUIRED_R4_MONITORING_METRICS:
            raise ValueError("R4 monitoring policy must inject every threshold exactly once")
        if type(self.minimum_observation_count) is not int or self.minimum_observation_count < 1:
            raise ValueError("R4 monitoring minimum observation count must be positive")
        if (
            type(self.maximum_observation_age_seconds) is not int
            or self.maximum_observation_age_seconds < 1
        ):
            raise ValueError("R4 monitoring maximum observation age must be positive")
        for field_name in (
            "expected_source_owner",
            "expected_pit_manifest_id",
            "expected_label_protocol_version",
            "expected_period_calendar_owner",
            "expected_period_calendar_id",
            "expected_period_calendar_version",
        ):
            _require_token(getattr(self, field_name), f"R4MonitoringPolicy.{field_name}")
        for field_name in (
            "expected_pit_manifest_hash",
            "expected_label_set_hash",
            "expected_data_schema_hash",
            "expected_period_calendar_hash",
        ):
            _require_hash(getattr(self, field_name), f"R4MonitoringPolicy.{field_name}")
        _require_text(
            self.expected_evidence_ref_prefix,
            "R4MonitoringPolicy.expected_evidence_ref_prefix",
        )
        _require_aware(self.recorded_at, "R4MonitoringPolicy.recorded_at")
        _require_aware(self.active_from, "R4MonitoringPolicy.active_from")
        _require_aware(self.active_until, "R4MonitoringPolicy.active_until")
        if not (
            self.active_decision.recorded_at
            <= self.recorded_at
            <= self.active_from
            < self.active_until
            <= self.active_decision.valid_until
        ):
            raise ValueError("R4 monitoring policy clocks exceed the active decision")
        if self.active_decision.outcome is not R4PromotionDecisionOutcome.APPROVED:
            raise ValueError("R4 monitoring policy requires an approved decision")
        if not _hashes_equal(
            self.expected_label_set_hash,
            self.active_decision.current_r3_content_hash,
        ):
            raise ValueError("R4 monitoring label baseline must bind the active R3 seal")
        object.__setattr__(self, "content_hash", r4_monitoring_policy_hash(self))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact policy is known and active at ``as_of``."""

        _require_aware(as_of, "R4MonitoringPolicy.as_of")
        return self.recorded_at <= as_of and self.active_from <= as_of < self.active_until

    def validated_copy(self) -> R4MonitoringPolicy:
        """Rebuild and revalidate every field of a potentially restored policy."""

        rebuilt = R4MonitoringPolicy(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            active_decision=self.active_decision,
            thresholds=tuple(_validated_threshold_copy(item) for item in self.thresholds),
            minimum_observation_count=self.minimum_observation_count,
            maximum_observation_age_seconds=self.maximum_observation_age_seconds,
            expected_source_owner=self.expected_source_owner,
            expected_pit_manifest_id=self.expected_pit_manifest_id,
            expected_pit_manifest_hash=self.expected_pit_manifest_hash,
            expected_label_protocol_version=self.expected_label_protocol_version,
            expected_label_set_hash=self.expected_label_set_hash,
            expected_data_schema_hash=self.expected_data_schema_hash,
            expected_period_calendar_owner=self.expected_period_calendar_owner,
            expected_period_calendar_id=self.expected_period_calendar_id,
            expected_period_calendar_version=self.expected_period_calendar_version,
            expected_period_calendar_hash=self.expected_period_calendar_hash,
            expected_evidence_ref_prefix=self.expected_evidence_ref_prefix,
            recorded_at=self.recorded_at,
            active_from=self.active_from,
            active_until=self.active_until,
        )
        if rebuilt != self:
            raise ValueError("R4 monitoring policy validated copy does not match its seal")
        return rebuilt


def r4_monitoring_policy_hash(policy: R4MonitoringPolicy) -> str:
    """Recompute the canonical monitoring-policy content seal."""

    return _hash_payload(
        {
            "schema": "research-r4-monitoring-policy.v1",
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "active_decision": _decision_identity_payload(policy.active_decision),
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
            "expected_source_owner": policy.expected_source_owner,
            "expected_pit_manifest_id": policy.expected_pit_manifest_id,
            "expected_pit_manifest_hash": policy.expected_pit_manifest_hash.lower(),
            "expected_label_protocol_version": policy.expected_label_protocol_version,
            "expected_label_set_hash": policy.expected_label_set_hash.lower(),
            "expected_data_schema_hash": policy.expected_data_schema_hash.lower(),
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


@dataclass(frozen=True)
class R4MonitoringMetricObservation:
    """One raw owner metric; missing values are never defaulted."""

    metric_key: R4MonitoringMetricKey
    unit: str
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R4MonitoringMetricKey):
            raise ValueError("R4 monitoring metric key is invalid")
        _require_token(self.unit, "R4MonitoringMetricObservation.unit", maximum=48)
        _require_metric_domain(
            self.metric_key,
            self.value,
            "R4MonitoringMetricObservation.value",
        )


@dataclass(frozen=True)
class R4MonitoringObservation:
    """Content-sealed post-promotion facts for one exact calendar member."""

    observation_id: str
    observation_version: str
    period_id: str
    period_calendar_id: str
    period_calendar_version: str
    period_calendar_hash: str
    period_start: datetime
    period_end: datetime
    active_decision: R4PromotionDecisionIdentity
    policy_id: str
    policy_version: str
    policy_hash: str
    source_owner: str
    portfolio_record_id: str
    portfolio_record_hash: str
    portfolio_record_content_hash: str
    r3_attestation_content_hash: str
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    evidence_ref: str
    label_protocol_version: str
    observed_label_set_hash: str
    observed_data_schema_hash: str
    metrics: tuple[R4MonitoringMetricObservation, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
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
            "portfolio_record_id",
            "pit_manifest_id",
            "label_protocol_version",
        ):
            _require_token(getattr(self, field_name), f"R4MonitoringObservation.{field_name}")
        for field_name in (
            "period_id",
            "period_calendar_hash",
            "policy_hash",
            "portfolio_record_hash",
            "portfolio_record_content_hash",
            "r3_attestation_content_hash",
            "pit_manifest_hash",
            "observed_label_set_hash",
            "observed_data_schema_hash",
        ):
            _require_hash(getattr(self, field_name), f"R4MonitoringObservation.{field_name}")
        _require_text(self.evidence_ref, "R4MonitoringObservation.evidence_ref")
        for field_name in (
            "period_start",
            "period_end",
            "observed_at",
            "available_at",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), f"R4MonitoringObservation.{field_name}")
        if not (
            self.period_start
            < self.period_end
            <= self.observed_at
            <= self.available_at
            <= self.recorded_at
            < self.valid_until
        ):
            raise ValueError("R4 monitoring observation clocks are invalid")
        expected_period_id = derive_r4_monitoring_period_id(
            calendar_id=self.period_calendar_id,
            calendar_version=self.period_calendar_version,
            period_start=self.period_start,
            period_end=self.period_end,
        )
        if not _hashes_equal(self.period_id, expected_period_id):
            raise ValueError("R4 monitoring observation period identity is not canonical")
        if not (
            self.research_only
            and self.must_not_use_for_decision
            and self.must_not_publish_current
            and self.must_not_execute
        ):
            raise ValueError("R4 monitoring facts cannot authorize production behavior")
        object.__setattr__(self, "content_hash", r4_monitoring_observation_hash(self))


def r4_monitoring_observation_hash(observation: R4MonitoringObservation) -> str:
    """Recompute one canonical raw-observation content seal."""

    return _hash_payload(
        {
            "schema": "research-r4-monitoring-observation.v1",
            "observation_id": observation.observation_id,
            "observation_version": observation.observation_version,
            "period_id": observation.period_id.lower(),
            "calendar": [
                observation.period_calendar_id,
                observation.period_calendar_version,
                observation.period_calendar_hash.lower(),
            ],
            "window": [
                _utc_text(observation.period_start),
                _utc_text(observation.period_end),
            ],
            "active_decision": _decision_identity_payload(observation.active_decision),
            "policy": [
                observation.policy_id,
                observation.policy_version,
                observation.policy_hash.lower(),
            ],
            "source_owner": observation.source_owner,
            "portfolio": [
                observation.portfolio_record_id,
                observation.portfolio_record_hash.lower(),
                observation.portfolio_record_content_hash.lower(),
            ],
            "r3_attestation_content_hash": observation.r3_attestation_content_hash.lower(),
            "clocks": [
                _utc_text(observation.observed_at),
                _utc_text(observation.available_at),
                _utc_text(observation.recorded_at),
                _utc_text(observation.valid_until),
            ],
            "pit_manifest": [
                observation.pit_manifest_id,
                observation.pit_manifest_hash.lower(),
            ],
            "evidence_ref": observation.evidence_ref,
            "label_protocol_version": observation.label_protocol_version,
            "observed_label_set_hash": observation.observed_label_set_hash.lower(),
            "observed_data_schema_hash": observation.observed_data_schema_hash.lower(),
            "metrics": [
                {
                    "metric_key": item.metric_key.value,
                    "unit": item.unit,
                    "value": _decimal_text(item.value),
                }
                for item in sorted(observation.metrics, key=lambda value: value.metric_key.value)
            ],
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_publish_current": True,
            "must_not_execute": True,
        }
    )


def _decision_identity_payload(identity: R4PromotionDecisionIdentity) -> dict[str, object]:
    return {
        "decision": [
            identity.decision_id,
            identity.decision_version,
            identity.content_hash.lower(),
            identity.outcome.value,
        ],
        "scope_hash": identity.scope.content_hash.lower(),
        "trial": [identity.trial_id, identity.trial_version, identity.trial_content_hash.lower()],
        "portfolio": [identity.portfolio_record_id, identity.portfolio_record_hash.lower()],
        "policy": [
            identity.policy_id,
            identity.policy_version,
            identity.policy_content_hash.lower(),
        ],
        "current_r3_content_hash": identity.current_r3_content_hash.lower(),
        "window": [
            _utc_text(identity.decided_at),
            _utc_text(identity.recorded_at),
            _utc_text(identity.valid_until),
        ],
    }


__all__ = [
    "REQUIRED_R4_MONITORING_METRICS",
    "R4MonitoringMetricKey",
    "R4MonitoringMetricObservation",
    "R4MonitoringObservation",
    "R4MonitoringPeriodCalendar",
    "R4MonitoringPeriodEntry",
    "R4MonitoringPolicy",
    "R4MonitoringThreshold",
    "R4MonitoringThresholdDirection",
    "derive_r4_monitoring_period_id",
    "r4_monitoring_observation_hash",
    "r4_monitoring_period_calendar_hash",
    "r4_monitoring_policy_hash",
]
