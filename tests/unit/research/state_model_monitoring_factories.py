"""Reusable exact R6 monitoring facts for unit and component tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.research.application.state_model_monitoring import ActiveR6QualificationEvidence
from apps.research.domain.state_model_monitoring import (
    REQUIRED_R6_MONITORING_METRICS,
    R6MonitoringMetricKey,
    R6MonitoringMetricObservation,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPeriodEntry,
    R6MonitoringPolicy,
    R6MonitoringThreshold,
    R6MonitoringThresholdDirection,
    derive_r6_monitoring_period_id,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)
QUALIFICATION_REF = R6QualificationRef(
    assessment_id="r6-qualification-assessment:test",
    assessment_hash="a" * 64,
)
EXPECTED_LABEL_HASH = "b" * 64
EXPECTED_PIT_MANIFEST_HASH = "d" * 64
EXPECTED_PIT_MANIFEST_ID = "r6-monitoring-pit-manifest-v1"
EXPECTED_SOURCE_OWNER = "research"
EXPECTED_EVIDENCE_REF_PREFIX = "research://r6/monitoring/"
EXPECTED_PERIOD_CALENDAR_ID = "r6-monitoring-calendar"
EXPECTED_PERIOD_CALENDAR_VERSION = "v1"

_AT_LEAST_KEYS = frozenset(
    {
        R6MonitoringMetricKey.TRANSITION_ACCURACY,
        R6MonitoringMetricKey.LABEL_STABILITY,
        R6MonitoringMetricKey.POLICY_ADJUSTED_R_SQUARED,
        R6MonitoringMetricKey.POLICY_RESIDUAL_AUTOCORRELATION_P_VALUE,
        R6MonitoringMetricKey.POLICY_HETEROSKEDASTICITY_P_VALUE,
        R6MonitoringMetricKey.POLICY_PARAMETER_STABILITY_P_VALUE,
    }
)


def thresholds() -> tuple[R6MonitoringThreshold, ...]:
    """Return one fully injected threshold family with no defaults."""

    return tuple(
        R6MonitoringThreshold(
            metric_key=key,
            unit="ratio" if key in _AT_LEAST_KEYS else "score",
            direction=(
                R6MonitoringThresholdDirection.AT_LEAST
                if key in _AT_LEAST_KEYS
                else R6MonitoringThresholdDirection.AT_MOST
            ),
            breach_threshold=(
                Decimal("0.6")
                if key in _AT_LEAST_KEYS
                else (
                    Decimal("10")
                    if key is R6MonitoringMetricKey.POLICY_CONDITION_NUMBER
                    else Decimal("0.4")
                )
            ),
            retirement_review_consecutive_breaches=2,
        )
        for key in sorted(REQUIRED_R6_MONITORING_METRICS, key=lambda item: item.value)
    )


def period_calendar() -> R6MonitoringPeriodCalendar:
    """Build the exact owner-recorded calendar used by monitoring facts."""

    valid_from = (NOW - timedelta(days=30)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    valid_until = valid_from + timedelta(days=61)
    entries = tuple(
        R6MonitoringPeriodEntry(
            period_id=derive_r6_monitoring_period_id(
                period_calendar_id=EXPECTED_PERIOD_CALENDAR_ID,
                period_calendar_version=EXPECTED_PERIOD_CALENDAR_VERSION,
                period_start=valid_from + timedelta(days=offset),
                period_end=valid_from + timedelta(days=offset + 1),
            ),
            period_start=valid_from + timedelta(days=offset),
            period_end=valid_from + timedelta(days=offset + 1),
        )
        for offset in range(61)
    )
    return R6MonitoringPeriodCalendar(
        source_owner=EXPECTED_SOURCE_OWNER,
        calendar_id=EXPECTED_PERIOD_CALENDAR_ID,
        calendar_version=EXPECTED_PERIOD_CALENDAR_VERSION,
        recorded_at=valid_from - timedelta(days=1),
        valid_from=valid_from,
        valid_until=valid_until,
        entries=entries,
    )


def policy(*, minimum_observation_count: int = 2) -> R6MonitoringPolicy:
    """Build an exact active monitoring policy."""

    monitoring_calendar = period_calendar()
    return R6MonitoringPolicy(
        policy_id="r6-monitoring-policy",
        policy_version="v1",
        qualification_ref=QUALIFICATION_REF,
        thresholds=thresholds(),
        minimum_observation_count=minimum_observation_count,
        maximum_observation_age_seconds=7 * 24 * 60 * 60,
        label_protocol_version="labels-v1",
        expected_label_set_hash=EXPECTED_LABEL_HASH,
        expected_source_owner=EXPECTED_SOURCE_OWNER,
        expected_pit_manifest_id=EXPECTED_PIT_MANIFEST_ID,
        expected_pit_manifest_hash=EXPECTED_PIT_MANIFEST_HASH,
        expected_period_calendar_owner=monitoring_calendar.source_owner,
        expected_period_calendar_id=EXPECTED_PERIOD_CALENDAR_ID,
        expected_period_calendar_version=EXPECTED_PERIOD_CALENDAR_VERSION,
        expected_period_calendar_hash=monitoring_calendar.content_hash,
        expected_evidence_ref_prefix=EXPECTED_EVIDENCE_REF_PREFIX,
        active_from=NOW - timedelta(days=30),
        active_until=NOW + timedelta(days=30),
    )


def healthy_metric_values() -> dict[R6MonitoringMetricKey, Decimal]:
    """Return values on the healthy side of every injected threshold."""

    return {
        key: (
            Decimal("0.8")
            if key in _AT_LEAST_KEYS
            else (
                Decimal("2")
                if key is R6MonitoringMetricKey.POLICY_CONDITION_NUMBER
                else Decimal("0.2")
            )
        )
        for key in REQUIRED_R6_MONITORING_METRICS
    }


def observation(
    *,
    sequence: int,
    monitoring_policy: R6MonitoringPolicy,
    values: dict[R6MonitoringMetricKey, Decimal] | None = None,
    metrics: tuple[R6MonitoringMetricObservation, ...] | None = None,
    observed_at: datetime | None = None,
    available_at: datetime | None = None,
    recorded_at: datetime | None = None,
    valid_until: datetime | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    period_calendar_id: str | None = None,
    period_calendar_version: str | None = None,
    period_calendar_hash: str | None = None,
    label_set_hash: str = EXPECTED_LABEL_HASH,
    source_owner: str | None = None,
    pit_manifest_id: str | None = None,
    pit_manifest_hash: str | None = None,
    evidence_ref: str | None = None,
) -> R6MonitoringObservation:
    """Build one sealed owner observation window."""

    effective_values = healthy_metric_values() if values is None else values
    metric_items = (
        tuple(
            R6MonitoringMetricObservation(
                metric_key=threshold.metric_key,
                unit=threshold.unit,
                value=effective_values[threshold.metric_key],
            )
            for threshold in monitoring_policy.thresholds
        )
        if metrics is None
        else metrics
    )
    effective_observed_at = observed_at or (NOW - timedelta(days=3 - sequence))
    effective_available_at = available_at or (effective_observed_at + timedelta(hours=1))
    effective_recorded_at = recorded_at or (effective_available_at + timedelta(hours=1))
    effective_period_start = period_start or effective_observed_at.astimezone(UTC).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    effective_period_end = period_end or (effective_period_start + timedelta(days=1))
    effective_calendar_id = period_calendar_id or monitoring_policy.expected_period_calendar_id
    effective_calendar_version = (
        period_calendar_version or monitoring_policy.expected_period_calendar_version
    )
    effective_calendar_hash = (
        period_calendar_hash or monitoring_policy.expected_period_calendar_hash
    )
    observation_period_id = derive_r6_monitoring_period_id(
        period_calendar_id=effective_calendar_id,
        period_calendar_version=effective_calendar_version,
        period_start=effective_period_start,
        period_end=effective_period_end,
    )
    return R6MonitoringObservation(
        observation_id=f"r6-monitoring-observation-{sequence}",
        observation_version="v1",
        observation_period_id=observation_period_id,
        period_calendar_id=effective_calendar_id,
        period_calendar_version=effective_calendar_version,
        period_calendar_hash=effective_calendar_hash,
        period_start=effective_period_start,
        period_end=effective_period_end,
        qualification_ref=QUALIFICATION_REF,
        policy_id=monitoring_policy.policy_id,
        policy_version=monitoring_policy.policy_version,
        policy_hash=monitoring_policy.content_hash,
        source_owner=source_owner or monitoring_policy.expected_source_owner,
        observed_at=effective_observed_at,
        available_at=effective_available_at,
        recorded_at=effective_recorded_at,
        valid_until=valid_until or (NOW + timedelta(days=1)),
        pit_manifest_id=pit_manifest_id or monitoring_policy.expected_pit_manifest_id,
        pit_manifest_hash=(pit_manifest_hash or monitoring_policy.expected_pit_manifest_hash),
        evidence_ref=(
            evidence_ref or f"{monitoring_policy.expected_evidence_ref_prefix}{sequence}"
        ),
        label_protocol_version=monitoring_policy.label_protocol_version,
        observed_label_set_hash=label_set_hash,
        metrics=metric_items,
    )


def active_qualification() -> ActiveR6QualificationEvidence:
    """Build a canonical active internal qualification projection."""

    return ActiveR6QualificationEvidence(
        qualification_ref=QUALIFICATION_REF,
        candidate_id="r6-candidate",
        candidate_version="v1",
        assessed_at=NOW - timedelta(days=10),
        known_at=NOW - timedelta(days=9),
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )


__all__ = [
    "EXPECTED_LABEL_HASH",
    "EXPECTED_PIT_MANIFEST_HASH",
    "EXPECTED_PIT_MANIFEST_ID",
    "EXPECTED_PERIOD_CALENDAR_ID",
    "EXPECTED_PERIOD_CALENDAR_VERSION",
    "EXPECTED_SOURCE_OWNER",
    "NOW",
    "QUALIFICATION_REF",
    "active_qualification",
    "healthy_metric_values",
    "observation",
    "period_calendar",
    "policy",
    "thresholds",
]
