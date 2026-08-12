"""Pure-domain contract tests for R4 post-promotion monitoring."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessment,
    R4MonitoringAssessmentStatus,
    R4MonitoringBlockerCode,
    R4MonitoringMetricKey,
    R4MonitoringMetricObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringThreshold,
    R4MonitoringThresholdDirection,
    evaluate_r4_promotion_monitoring,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    DATA_SCHEMA_HASH,
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)


def _evaluate(
    *,
    observations: tuple,
    policy_override=None,
    calendar_override=None,
) -> R4MonitoringAssessment:
    decision = monitoring_decision()
    calendar = calendar_override or monitoring_calendar(decision)
    policy = policy_override or monitoring_policy(decision, calendar)
    return evaluate_r4_promotion_monitoring(
        requested_active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=calendar.valid_from + timedelta(hours=2, minutes=30),
    )


def test_active_old_evidence_requires_review_after_consecutive_new_breaches() -> None:
    """New degraded outcomes must not leave an old ACTIVE decision silently current."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    degraded = {R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("-0.10")}
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
            value_overrides=degraded,
        )
        for index in range(2)
    )

    assessment = _evaluate(observations=observations, policy_override=policy)

    assert assessment.status is R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.retirement_review_required is True
    assert assessment.automatic_retirement is False
    assert assessment.must_not_publish_current is True
    assert assessment.must_not_execute is True


def test_healthy_and_single_latest_breach_are_distinct_states() -> None:
    """One latest breach is visible but does not bypass the consecutive rule."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    healthy = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    assert _evaluate(observations=healthy, policy_override=policy).status is (
        R4MonitoringAssessmentStatus.HEALTHY
    )

    latest_breach = (
        healthy[0],
        monitoring_observation(
            period_index=1,
            decision=decision,
            calendar=calendar,
            policy=policy,
            value_overrides={R4MonitoringMetricKey.RELATIVE_NET_RETURN: Decimal("-0.01")},
        ),
    )
    result = _evaluate(observations=latest_breach, policy_override=policy)
    assert result.status is R4MonitoringAssessmentStatus.BREACHED
    assert result.retirement_review_required is False


@pytest.mark.parametrize(
    ("label_hash", "data_hash", "label_drift", "data_drift"),
    (("f" * 64, DATA_SCHEMA_HASH, True, False), (None, "c" * 64, False, True)),
)
def test_label_or_data_drift_requires_human_review(
    label_hash: str | None,
    data_hash: str,
    label_drift: bool,
    data_drift: bool,
) -> None:
    """A changed label set or data schema cannot remain silently healthy."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
            observed_label_set_hash=label_hash,
            observed_data_schema_hash=data_hash,
        )
        for index in range(2)
    )

    result = _evaluate(observations=observations, policy_override=policy)

    assert result.status is R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert result.label_drift_detected is label_drift
    assert result.data_drift_detected is data_drift


def test_missing_middle_period_and_future_period_fail_closed() -> None:
    """Only the exact complete prefix of canonical completed periods is accepted."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    first = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    second = monitoring_observation(
        period_index=1,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    future = monitoring_observation(
        period_index=2,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )

    missing = _evaluate(observations=(second,), policy_override=policy)
    assert missing.status is R4MonitoringAssessmentStatus.BLOCKED
    assert R4MonitoringBlockerCode.OBSERVATION_PERIOD_COVERAGE_INCOMPLETE in missing.blockers

    from_future = _evaluate(observations=(first, second, future), policy_override=policy)
    assert from_future.status is R4MonitoringAssessmentStatus.BLOCKED
    assert R4MonitoringBlockerCode.OBSERVATION_PERIOD_FROM_FUTURE in from_future.blockers


def test_stale_observation_and_owner_substitution_fail_closed() -> None:
    """Freshness and exact raw-fact ownership are mandatory."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    stale_policy = replace(
        monitoring_policy(decision, calendar),
        maximum_observation_age_seconds=60,
    )
    stale_observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=stale_policy,
        )
        for index in range(2)
    )
    stale = _evaluate(observations=stale_observations, policy_override=stale_policy)
    assert stale.status is R4MonitoringAssessmentStatus.BLOCKED
    assert R4MonitoringBlockerCode.OBSERVATION_STALE in stale.blockers

    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    substituted = replace(observations[-1], source_owner="caller")
    owner_result = _evaluate(
        observations=(observations[0], substituted),
        policy_override=policy,
    )
    assert R4MonitoringBlockerCode.OBSERVATION_OWNER_MISMATCH in owner_result.blockers


def test_policy_tamper_missing_metric_and_unit_substitution_are_blocked() -> None:
    """A seal or semantic metric-set mismatch cannot evaluate healthy."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    object.__setattr__(policy, "content_hash", "0" * 64)
    tampered = _evaluate(observations=observations, policy_override=policy)
    assert R4MonitoringBlockerCode.POLICY_HASH_MISMATCH in tampered.blockers

    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    missing_metrics = replace(observations[-1], metrics=observations[-1].metrics[:-1])
    missing = _evaluate(
        observations=(observations[0], missing_metrics),
        policy_override=policy,
    )
    assert R4MonitoringBlockerCode.METRIC_MISSING in missing.blockers

    wrong_metric = replace(observations[-1].metrics[0], unit="wrong-unit")
    wrong_units = replace(
        observations[-1],
        metrics=(wrong_metric, *observations[-1].metrics[1:]),
    )
    unit_result = _evaluate(
        observations=(observations[0], wrong_units),
        policy_override=policy,
    )
    assert R4MonitoringBlockerCode.METRIC_UNIT_MISMATCH in unit_result.blockers


def test_policy_and_fact_hashes_are_canonical_over_metric_order() -> None:
    """Caller tuple order cannot alter content-addressed policy or facts."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    reversed_policy = replace(policy, thresholds=tuple(reversed(policy.thresholds)))
    observation = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    reversed_observation = replace(
        observation,
        metrics=tuple(reversed(observation.metrics)),
    )

    assert reversed_policy.content_hash == policy.content_hash
    assert reversed_observation.content_hash == observation.content_hash


def test_calendar_gaps_and_invalid_metric_domains_are_rejected() -> None:
    """Calendar aliases and impossible raw values cannot be minted."""

    calendar = monitoring_calendar()
    first = calendar.entries[0]
    third = calendar.entries[2]
    with pytest.raises(ValueError, match="contiguous"):
        R4MonitoringPeriodCalendar(
            source_owner=calendar.source_owner,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            recorded_at=calendar.recorded_at,
            valid_from=first.period_start,
            valid_until=third.period_end,
            entries=(first, third),
        )

    with pytest.raises(ValueError, match="at least one"):
        R4MonitoringMetricObservation(
            metric_key=R4MonitoringMetricKey.COVARIANCE_CONDITION_NUMBER,
            unit="dimensionless",
            value=Decimal("0"),
        )
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        R4MonitoringThreshold(
            metric_key=R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO,
            unit="ratio",
            direction=R4MonitoringThresholdDirection.AT_LEAST,
            breach_threshold=Decimal("1.1"),
            retirement_review_consecutive_breaches=2,
        )


def test_policy_rejects_semantically_reversed_metric_direction() -> None:
    """A content-addressed policy cannot redefine which direction is healthy."""

    with pytest.raises(ValueError, match="canonical direction"):
        R4MonitoringThreshold(
            metric_key=R4MonitoringMetricKey.COVARIANCE_COVERAGE_RATIO,
            unit="ratio",
            direction=R4MonitoringThresholdDirection.AT_MOST,
            breach_threshold=Decimal("0.80"),
            retirement_review_consecutive_breaches=2,
        )


def test_late_reporting_cannot_refresh_an_old_canonical_period() -> None:
    """Freshness is measured from period_end rather than a late report clock."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = replace(
        monitoring_policy(decision, calendar),
        maximum_observation_age_seconds=60,
    )
    first = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    latest = monitoring_observation(
        period_index=1,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    evaluated_at = calendar.valid_from + timedelta(hours=2, minutes=30)
    late_clock = evaluated_at - timedelta(seconds=30)
    late_report = replace(
        latest,
        observed_at=late_clock,
        available_at=late_clock,
        recorded_at=late_clock,
    )

    result = _evaluate(
        observations=(first, late_report),
        policy_override=policy,
    )

    assert result.status is R4MonitoringAssessmentStatus.BLOCKED
    assert R4MonitoringBlockerCode.OBSERVATION_STALE in result.blockers


def test_drift_in_any_completed_period_requires_review() -> None:
    """A later healthy fact cannot erase label/data drift from a completed period."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observations = (
        monitoring_observation(
            period_index=0,
            decision=decision,
            calendar=calendar,
            policy=policy,
            observed_label_set_hash="f" * 64,
        ),
        monitoring_observation(
            period_index=1,
            decision=decision,
            calendar=calendar,
            policy=policy,
        ),
    )

    result = _evaluate(observations=observations, policy_override=policy)

    assert result.status is R4MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert result.label_drift_detected is True


def test_validated_policy_copy_and_assessment_shape_recheck_frozen_values() -> None:
    """Live validation rejects tampered policy and impossible assessment shapes."""

    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    assert policy.validated_copy() == policy
    object.__setattr__(policy.thresholds[0], "direction", R4MonitoringThresholdDirection.AT_MOST)
    with pytest.raises(ValueError, match="canonical direction"):
        policy.validated_copy()

    policy = monitoring_policy(decision, calendar)
    observations = tuple(
        monitoring_observation(
            period_index=index,
            decision=decision,
            calendar=calendar,
            policy=policy,
        )
        for index in range(2)
    )
    healthy = _evaluate(observations=observations, policy_override=policy)
    with pytest.raises(ValueError, match="every required metric"):
        replace(healthy, metric_results=healthy.metric_results[:-1])
    with pytest.raises(ValueError, match="drift"):
        replace(healthy, label_drift_detected=True)
