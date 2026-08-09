"""Synthetic factories for R4 post-promotion monitoring tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringMetricKey,
    R4MonitoringMetricObservation,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPeriodEntry,
    R4MonitoringPolicy,
    R4MonitoringThreshold,
    R4MonitoringThresholdDirection,
    derive_r4_monitoring_period_id,
)
from tests.unit.research.r4_promotion_factories import promotion_decision

CALENDAR_ID = "r4-hourly-monitoring-calendar"
CALENDAR_VERSION = "calendar.v1"
PIT_MANIFEST_ID = "r4-monitoring-pit-manifest"
PIT_MANIFEST_HASH = "e" * 64
DATA_SCHEMA_HASH = "d" * 64


def monitoring_decision() -> R4PromotionDecision:
    """Return the exact approved decision being monitored."""

    return promotion_decision()


def monitoring_calendar(
    decision: R4PromotionDecision | None = None,
) -> R4MonitoringPeriodCalendar:
    """Return four contiguous canonical hourly monitoring periods."""

    selected = decision or monitoring_decision()
    start = selected.recorded_at + timedelta(minutes=56)
    entries = tuple(
        R4MonitoringPeriodEntry(
            period_id=derive_r4_monitoring_period_id(
                calendar_id=CALENDAR_ID,
                calendar_version=CALENDAR_VERSION,
                period_start=start + timedelta(hours=index),
                period_end=start + timedelta(hours=index + 1),
            ),
            period_start=start + timedelta(hours=index),
            period_end=start + timedelta(hours=index + 1),
        )
        for index in range(4)
    )
    return R4MonitoringPeriodCalendar(
        source_owner="research",
        calendar_id=CALENDAR_ID,
        calendar_version=CALENDAR_VERSION,
        recorded_at=selected.recorded_at + timedelta(minutes=10),
        valid_from=start,
        valid_until=start + timedelta(hours=4),
        entries=entries,
    )


def monitoring_thresholds() -> tuple[R4MonitoringThreshold, ...]:
    """Return every explicit threshold without relying on code defaults."""

    specifications = (
        (
            R4MonitoringMetricKey.RELATIVE_NET_RETURN,
            R4MonitoringThresholdDirection.AT_LEAST,
            Decimal("0"),
        ),
        (
            R4MonitoringMetricKey.RELATIVE_DRAWDOWN_INCREASE,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.10"),
        ),
        (
            R4MonitoringMetricKey.RELATIVE_VOLATILITY_INCREASE,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.10"),
        ),
        (
            R4MonitoringMetricKey.RELATIVE_COST_INCREASE,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.05"),
        ),
        (
            R4MonitoringMetricKey.COVARIANCE_CONDITION_NUMBER,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("100"),
        ),
        (
            R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO,
            R4MonitoringThresholdDirection.AT_LEAST,
            Decimal("0.80"),
        ),
        (
            R4MonitoringMetricKey.RISK_CONTRIBUTION_ERROR,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.05"),
        ),
        (
            R4MonitoringMetricKey.BETA_DRIFT,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.20"),
        ),
        (
            R4MonitoringMetricKey.REGIME_STABILITY_RATIO,
            R4MonitoringThresholdDirection.AT_LEAST,
            Decimal("0.70"),
        ),
        (
            R4MonitoringMetricKey.LABEL_DRIFT_RATIO,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.10"),
        ),
        (
            R4MonitoringMetricKey.DATA_DRIFT_RATIO,
            R4MonitoringThresholdDirection.AT_MOST,
            Decimal("0.20"),
        ),
    )
    return tuple(
        R4MonitoringThreshold(
            metric_key=key,
            unit=(
                "dimensionless"
                if key is R4MonitoringMetricKey.COVARIANCE_CONDITION_NUMBER
                else "ratio"
            ),
            direction=direction,
            breach_threshold=threshold,
            retirement_review_consecutive_breaches=2,
        )
        for key, direction, threshold in specifications
    )


def monitoring_policy(
    decision: R4PromotionDecision | None = None,
    calendar: R4MonitoringPeriodCalendar | None = None,
) -> R4MonitoringPolicy:
    """Return one exact monitoring policy bound to decision and calendar."""

    selected_decision = decision or monitoring_decision()
    selected_calendar = calendar or monitoring_calendar(selected_decision)
    return R4MonitoringPolicy(
        policy_id="r4-post-promotion-monitoring",
        policy_version="policy.v1",
        active_decision=R4PromotionDecisionIdentity.from_decision(selected_decision),
        thresholds=monitoring_thresholds(),
        minimum_observation_count=2,
        maximum_observation_age_seconds=7200,
        expected_source_owner="portfolio",
        expected_pit_manifest_id=PIT_MANIFEST_ID,
        expected_pit_manifest_hash=PIT_MANIFEST_HASH,
        expected_label_protocol_version="r3-labels.v1",
        expected_label_set_hash=(selected_decision.trial.current_r3_attestation.content_hash),
        expected_data_schema_hash=DATA_SCHEMA_HASH,
        expected_period_calendar_owner=selected_calendar.source_owner,
        expected_period_calendar_id=selected_calendar.calendar_id,
        expected_period_calendar_version=selected_calendar.calendar_version,
        expected_period_calendar_hash=selected_calendar.content_hash,
        expected_evidence_ref_prefix="portfolio:r4-monitoring:",
        recorded_at=selected_decision.recorded_at + timedelta(minutes=20),
        active_from=selected_calendar.valid_from,
        active_until=selected_calendar.valid_until,
    )


def healthy_metric_values() -> dict[R4MonitoringMetricKey, Decimal]:
    """Return semantically valid healthy values for all required metrics."""

    return {
        R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("0.03"),
        R4MonitoringMetricKey.RELATIVE_DRAWDOWN_INCREASE: Decimal("0.01"),
        R4MonitoringMetricKey.RELATIVE_VOLATILITY_INCREASE: Decimal("0.01"),
        R4MonitoringMetricKey.RELATIVE_COST_INCREASE: Decimal("0.01"),
        R4MonitoringMetricKey.COVARIANCE_CONDITION_NUMBER: Decimal("10"),
        R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO: Decimal("0.95"),
        R4MonitoringMetricKey.RISK_CONTRIBUTION_ERROR: Decimal("0.01"),
        R4MonitoringMetricKey.BETA_DRIFT: Decimal("0.02"),
        R4MonitoringMetricKey.REGIME_STABILITY_RATIO: Decimal("0.90"),
        R4MonitoringMetricKey.LABEL_DRIFT_RATIO: Decimal("0.01"),
        R4MonitoringMetricKey.DATA_DRIFT_RATIO: Decimal("0.02"),
    }


def monitoring_observation(
    *,
    period_index: int,
    decision: R4PromotionDecision | None = None,
    calendar: R4MonitoringPeriodCalendar | None = None,
    policy: R4MonitoringPolicy | None = None,
    value_overrides: dict[R4MonitoringMetricKey, Decimal] | None = None,
    observed_label_set_hash: str | None = None,
    observed_data_schema_hash: str | None = None,
) -> R4MonitoringObservation:
    """Return one owner-sealed raw observation for an exact calendar member."""

    selected_decision = decision or monitoring_decision()
    selected_calendar = calendar or monitoring_calendar(selected_decision)
    selected_policy = policy or monitoring_policy(selected_decision, selected_calendar)
    entry = selected_calendar.entries[period_index]
    values = healthy_metric_values()
    values.update(value_overrides or {})
    thresholds = {item.metric_key: item for item in selected_policy.thresholds}
    record = selected_decision.trial.portfolio_record
    r3 = selected_decision.trial.current_r3_attestation
    return R4MonitoringObservation(
        observation_id=f"r4-monitoring-observation-{period_index}",
        observation_version="observation.v1",
        period_id=entry.period_id,
        period_calendar_id=selected_calendar.calendar_id,
        period_calendar_version=selected_calendar.calendar_version,
        period_calendar_hash=selected_calendar.content_hash,
        period_start=entry.period_start,
        period_end=entry.period_end,
        active_decision=R4PromotionDecisionIdentity.from_decision(selected_decision),
        policy_id=selected_policy.policy_id,
        policy_version=selected_policy.policy_version,
        policy_hash=selected_policy.content_hash,
        source_owner="portfolio",
        portfolio_record_id=record.record_id,
        portfolio_record_hash=record.record_hash,
        portfolio_record_content_hash=record.content_hash,
        r3_attestation_content_hash=r3.content_hash,
        observed_at=entry.period_end,
        available_at=entry.period_end + timedelta(minutes=1),
        recorded_at=entry.period_end + timedelta(minutes=2),
        valid_until=selected_calendar.valid_until,
        pit_manifest_id=PIT_MANIFEST_ID,
        pit_manifest_hash=PIT_MANIFEST_HASH,
        evidence_ref=f"portfolio:r4-monitoring:{period_index}",
        label_protocol_version="r3-labels.v1",
        observed_label_set_hash=observed_label_set_hash or r3.content_hash,
        observed_data_schema_hash=observed_data_schema_hash or DATA_SCHEMA_HASH,
        metrics=tuple(
            R4MonitoringMetricObservation(
                metric_key=key,
                unit=thresholds[key].unit,
                value=value,
            )
            for key, value in sorted(values.items(), key=lambda item: item[0].value)
        ),
    )


__all__ = [
    "DATA_SCHEMA_HASH",
    "PIT_MANIFEST_HASH",
    "PIT_MANIFEST_ID",
    "healthy_metric_values",
    "monitoring_calendar",
    "monitoring_decision",
    "monitoring_observation",
    "monitoring_policy",
    "monitoring_thresholds",
]
