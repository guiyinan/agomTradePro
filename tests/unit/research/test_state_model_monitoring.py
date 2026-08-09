"""Pure R6 monitoring policy, evidence, and assessment tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessmentStatus,
    R6MonitoringBlockerCode,
    R6MonitoringMetricKey,
    R6MonitoringMetricObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
    evaluate_r6_monitoring,
)
from tests.unit.research.state_model_monitoring_factories import (
    NOW,
    QUALIFICATION_REF,
    active_qualification,
    healthy_metric_values,
    observation,
    period_calendar,
    policy,
    thresholds,
)


def _evaluate(
    *,
    monitoring_policy: R6MonitoringPolicy,
    observations,
    monitoring_calendar: R6MonitoringPeriodCalendar | None = None,
):
    qualification = active_qualification()
    return evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=monitoring_policy.policy_id,
        requested_policy_version=monitoring_policy.policy_version,
        expected_policy_hash=monitoring_policy.content_hash,
        policy=monitoring_policy,
        period_calendar=monitoring_calendar or period_calendar(),
        observations=tuple(observations),
        evaluated_at=NOW,
    )


def test_period_calendar_manifest_covers_its_full_validity_without_gaps() -> None:
    """A self-consistent hash cannot bless gaps or an early final cutoff."""

    canonical = period_calendar()
    with pytest.raises(ValueError, match="contiguous"):
        replace(
            canonical,
            entries=canonical.entries[:10] + canonical.entries[11:],
        )
    with pytest.raises(ValueError, match="full validity"):
        replace(canonical, entries=canonical.entries[:-1])


def test_calendar_forward_horizon_must_cover_the_policy_active_window() -> None:
    """A shorter but internally contiguous manifest cannot end policy monitoring early."""

    canonical = period_calendar()
    truncated = replace(
        canonical,
        valid_until=canonical.entries[-2].period_end,
        entries=canonical.entries[:-1],
    )
    monitoring_policy = replace(
        policy(),
        expected_period_calendar_hash=truncated.content_hash,
    )

    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        monitoring_calendar=truncated,
        observations=(),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_HORIZON_INSUFFICIENT in (assessment.blockers)


def test_policy_recording_cannot_predate_exact_active_qualification_knowledge() -> None:
    """The policy owner clock must follow both qualification assessment and knowledge."""

    qualification = active_qualification()
    monitoring_policy = replace(
        policy(),
        recorded_at=qualification.known_at - timedelta(microseconds=1),
    )

    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_QUALIFICATION_CAUSALITY_INVALID in (assessment.blockers)


def test_policy_requires_every_threshold_to_be_injected() -> None:
    """No missing threshold may be filled by a code default."""

    monitoring_calendar = period_calendar()
    with pytest.raises(ValueError, match="every required threshold"):
        R6MonitoringPolicy(
            policy_id="r6-monitoring-policy",
            policy_version="v1",
            qualification_ref=QUALIFICATION_REF,
            thresholds=thresholds()[:-1],
            minimum_observation_count=2,
            maximum_observation_age_seconds=3600,
            label_protocol_version="labels-v1",
            expected_label_set_hash="b" * 64,
            expected_source_owner="research",
            expected_pit_manifest_id="r6-monitoring-pit-manifest-v1",
            expected_pit_manifest_hash="d" * 64,
            expected_period_calendar_owner=monitoring_calendar.source_owner,
            expected_period_calendar_id="r6-monitoring-calendar",
            expected_period_calendar_version="v1",
            expected_period_calendar_hash=monitoring_calendar.content_hash,
            expected_evidence_ref_prefix="research://r6/monitoring/",
            recorded_at=NOW - timedelta(days=2),
            active_from=NOW - timedelta(days=1),
            active_until=NOW + timedelta(days=1),
        )


def test_healthy_raw_facts_remain_internal_and_non_executable() -> None:
    """Complete healthy facts produce no lifecycle or production authority."""

    monitoring_policy = policy()
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(
            observation(sequence=1, monitoring_policy=monitoring_policy),
            observation(sequence=2, monitoring_policy=monitoring_policy),
        ),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.HEALTHY
    assert assessment.retirement_review_required is False
    assert assessment.automatic_retirement is False
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True
    assert assessment.must_not_publish_current is True
    assert assessment.must_not_execute is True


def test_reversed_observation_order_is_fail_closed() -> None:
    """Owner ordering is contractual and cannot be silently rewritten."""

    monitoring_policy = policy()
    first = observation(sequence=1, monitoring_policy=monitoring_policy)
    second = observation(sequence=2, monitoring_policy=monitoring_policy)

    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(second, first),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_ORDER_INVALID in assessment.blockers


def test_missing_middle_calendar_member_is_fail_closed() -> None:
    """An older extra period cannot replace a missing member in the selected range."""

    monitoring_policy = policy(
        minimum_observation_count=3,
        maximum_observation_age_seconds=3 * 24 * 60 * 60,
    )
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(
            observation(sequence=-1, monitoring_policy=monitoring_policy),
            observation(sequence=0, monitoring_policy=monitoring_policy),
            observation(sequence=2, monitoring_policy=monitoring_policy),
        ),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_COVERAGE_INCOMPLETE in assessment.blockers


def test_unfinished_calendar_window_is_fail_closed() -> None:
    """A canonical period is unusable until its exact window has completed."""

    monitoring_policy = policy(minimum_observation_count=1)
    start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    fact = observation(
        sequence=3,
        monitoring_policy=monitoring_policy,
        period_start=start,
        period_end=start + timedelta(days=1),
        observed_at=NOW - timedelta(microseconds=1),
        available_at=NOW,
        recorded_at=NOW,
    )

    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_INCOMPLETE in assessment.blockers


def test_policy_owner_recorded_after_cutoff_is_fail_closed() -> None:
    """An otherwise sealed policy cannot be used before its owner knowledge clock."""

    monitoring_policy = replace(
        policy(),
        recorded_at=NOW + timedelta(hours=1),
        active_from=NOW + timedelta(hours=2),
        active_until=NOW + timedelta(days=1),
    )

    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_FROM_FUTURE in assessment.blockers


def test_single_latest_threshold_breach_does_not_request_retirement_review() -> None:
    """A first breach remains visible but cannot retire an internal qualification."""

    monitoring_policy = policy()
    breached_values = healthy_metric_values()
    breached_values[R6MonitoringMetricKey.LOG_LOSS] = Decimal("0.5")
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(
            observation(sequence=1, monitoring_policy=monitoring_policy),
            observation(
                sequence=2,
                monitoring_policy=monitoring_policy,
                values=breached_values,
            ),
        ),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BREACHED
    assert assessment.retirement_review_required is False
    result = next(
        item
        for item in assessment.metric_results
        if item.metric_key is R6MonitoringMetricKey.LOG_LOSS
    )
    assert result.trailing_consecutive_breaches == 1


def test_consecutive_breaches_only_request_manual_retirement_review() -> None:
    """Injected consecutive-breach policy derives review without auto-retirement."""

    monitoring_policy = policy()
    breached_values = healthy_metric_values()
    breached_values[R6MonitoringMetricKey.DECISION_LOSS] = Decimal("0.5")
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(
            observation(
                sequence=1,
                monitoring_policy=monitoring_policy,
                values=breached_values,
            ),
            observation(
                sequence=2,
                monitoring_policy=monitoring_policy,
                values=breached_values,
            ),
        ),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.retirement_review_required is True
    assert assessment.automatic_retirement is False


def test_label_drift_requests_review_without_replacing_regime() -> None:
    """A changed economic label set is a review trigger, never a Regime write."""

    monitoring_policy = policy()
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(
            observation(sequence=1, monitoring_policy=monitoring_policy),
            observation(
                sequence=2,
                monitoring_policy=monitoring_policy,
                label_set_hash="c" * 64,
            ),
        ),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.label_drift_detected is True
    assert assessment.must_not_replace_regime is True


@pytest.mark.parametrize(
    ("mutate_metrics", "expected_blocker"),
    [
        (
            lambda metrics: metrics[:-1],
            R6MonitoringBlockerCode.METRIC_MISSING,
        ),
        (
            lambda metrics: metrics + (metrics[0],),
            R6MonitoringBlockerCode.METRIC_DUPLICATE,
        ),
        (
            lambda metrics: (
                replace(metrics[0], unit=""),
                *metrics[1:],
            ),
            R6MonitoringBlockerCode.METRIC_UNIT_MISSING,
        ),
        (
            lambda metrics: (
                replace(metrics[0], unit="wrong-unit"),
                *metrics[1:],
            ),
            R6MonitoringBlockerCode.METRIC_UNIT_MISMATCH,
        ),
    ],
)
def test_incomplete_or_ambiguous_metric_evidence_is_blocked(
    mutate_metrics,
    expected_blocker: R6MonitoringBlockerCode,
) -> None:
    """Missing, duplicate, or unit-ambiguous owner facts fail closed."""

    monitoring_policy = policy(minimum_observation_count=1)
    complete = observation(sequence=1, monitoring_policy=monitoring_policy)
    incomplete = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        metrics=tuple(mutate_metrics(complete.metrics)),
    )
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(incomplete,),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert expected_blocker in assessment.blockers
    assert assessment.retirement_review_required is False


def test_empty_owner_evidence_is_blocked() -> None:
    """An empty canonical owner result cannot be interpreted as healthy."""

    monitoring_policy = policy()
    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATIONS_MISSING in assessment.blockers


@pytest.mark.parametrize(
    ("fact_kwargs", "expected_blocker"),
    [
        (
            {
                "observed_at": NOW + timedelta(hours=1),
                "available_at": NOW + timedelta(hours=2),
                "recorded_at": NOW + timedelta(hours=3),
                "valid_until": NOW + timedelta(days=1),
            },
            R6MonitoringBlockerCode.OBSERVATION_FROM_FUTURE,
        ),
        (
            {"valid_until": NOW},
            R6MonitoringBlockerCode.OBSERVATION_STALE,
        ),
    ],
)
def test_future_or_exactly_expired_owner_evidence_is_blocked(
    fact_kwargs: dict[str, object],
    expected_blocker: R6MonitoringBlockerCode,
) -> None:
    """Observation clocks preserve PIT knowledge and exact-expiry semantics."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        **fact_kwargs,
    )
    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert expected_blocker in assessment.blockers


def test_owner_recorded_at_after_as_of_is_future_evidence() -> None:
    """Past observation/release clocks cannot hide a future owner recording clock."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        recorded_at=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(days=1),
    )
    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_FROM_FUTURE in assessment.blockers


def test_same_period_microsecond_shift_cannot_control_latest_by_hash() -> None:
    """A calendar alias plus timestamp nudge cannot create a second window."""

    monitoring_policy = policy()
    first = observation(sequence=1, monitoring_policy=monitoring_policy)
    breached_values = healthy_metric_values()
    breached_values[R6MonitoringMetricKey.LOG_LOSS] = Decimal("0.5")
    competing = observation(
        sequence=2,
        monitoring_policy=monitoring_policy,
        values=breached_values,
        period_start=first.period_start,
        period_end=first.period_end,
        period_calendar_version="attacker-v2",
        period_calendar_hash="e" * 64,
        observed_at=first.observed_at + timedelta(microseconds=1),
        available_at=first.available_at + timedelta(microseconds=1),
        recorded_at=first.recorded_at + timedelta(microseconds=1),
    )
    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(first, competing),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert competing.observation_period_id != first.observation_period_id
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_OVERLAP in assessment.blockers
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_MISMATCH in assessment.blockers


def test_adjacent_micro_windows_cannot_replace_canonical_calendar_member() -> None:
    """Two derived non-overlapping micro-windows cannot control the latest value."""

    monitoring_policy = policy()
    canonical_entry = next(
        item
        for item in period_calendar().entries
        if item.period_start <= NOW - timedelta(days=2) < item.period_end
    )
    split_start = canonical_entry.period_start
    split_middle = split_start + timedelta(microseconds=1)
    split_end = split_middle + timedelta(microseconds=1)
    first = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        period_start=split_start,
        period_end=split_middle,
        observed_at=split_start,
        available_at=split_start + timedelta(hours=1),
        recorded_at=split_start + timedelta(hours=2),
    )
    breached_values = healthy_metric_values()
    breached_values[R6MonitoringMetricKey.LOG_LOSS] = Decimal("0.5")
    attacker_latest = observation(
        sequence=2,
        monitoring_policy=monitoring_policy,
        values=breached_values,
        period_start=split_middle,
        period_end=split_end,
        observed_at=split_middle,
        available_at=split_middle + timedelta(hours=1),
        recorded_at=split_middle + timedelta(hours=2),
    )

    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(first, attacker_latest),
    )

    assert first.period_end == attacker_latest.period_start
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_OVERLAP not in assessment.blockers
    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_NOT_IN_CALENDAR in assessment.blockers


@pytest.mark.parametrize(
    ("metric_key", "invalid_value"),
    [
        (R6MonitoringMetricKey.TRANSITION_ACCURACY, Decimal("-0.01")),
        (R6MonitoringMetricKey.LOG_LOSS, Decimal("-0.01")),
        (R6MonitoringMetricKey.CALIBRATION_ERROR, Decimal("-0.01")),
        (R6MonitoringMetricKey.DURATION_MAE, Decimal("-0.01")),
        (R6MonitoringMetricKey.DECISION_LOSS, Decimal("-0.01")),
        (R6MonitoringMetricKey.LABEL_STABILITY, Decimal("1.01")),
        (R6MonitoringMetricKey.POLICY_ADJUSTED_R_SQUARED, Decimal("1.01")),
        (
            R6MonitoringMetricKey.POLICY_RESIDUAL_AUTOCORRELATION_P_VALUE,
            Decimal("-0.01"),
        ),
        (
            R6MonitoringMetricKey.POLICY_HETEROSKEDASTICITY_P_VALUE,
            Decimal("1.01"),
        ),
        (
            R6MonitoringMetricKey.POLICY_PARAMETER_STABILITY_P_VALUE,
            Decimal("-0.01"),
        ),
        (R6MonitoringMetricKey.POLICY_CONDITION_NUMBER, Decimal("0.999")),
    ],
)
def test_invalid_raw_metric_domains_are_rejected(
    metric_key: R6MonitoringMetricKey,
    invalid_value: Decimal,
) -> None:
    """Each metric's mathematical domain is enforced before assessment."""

    with pytest.raises(ValueError):
        R6MonitoringMetricObservation(
            metric_key=metric_key,
            unit="score",
            value=invalid_value,
        )


def test_adjusted_r_squared_allows_negative_values_and_condition_number_allows_one() -> None:
    """Valid statistical boundary values remain representable."""

    adjusted = R6MonitoringMetricObservation(
        metric_key=R6MonitoringMetricKey.POLICY_ADJUSTED_R_SQUARED,
        unit="ratio",
        value=Decimal("-7.5"),
    )
    condition = R6MonitoringMetricObservation(
        metric_key=R6MonitoringMetricKey.POLICY_CONDITION_NUMBER,
        unit="score",
        value=Decimal("1"),
    )

    assert adjusted.value == Decimal("-7.5")
    assert condition.value == Decimal("1")


def test_metric_tuple_order_cannot_change_observation_hash() -> None:
    """Raw metrics are a semantic set sealed in canonical metric-key order."""

    monitoring_policy = policy(minimum_observation_count=1)
    original = observation(sequence=1, monitoring_policy=monitoring_policy)
    reordered = replace(original, metrics=tuple(reversed(original.metrics)))

    assert reordered.content_hash == original.content_hash


def test_distinct_period_ids_cannot_hide_overlapping_windows() -> None:
    """Window ordering rejects partial overlap even when derived IDs differ."""

    monitoring_policy = policy()
    first_start = NOW - timedelta(days=3)
    first_end = NOW - timedelta(days=1)
    second_start = NOW - timedelta(days=2)
    second_end = NOW
    first_period = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        period_start=first_start,
        period_end=first_end,
        observed_at=NOW - timedelta(days=2),
        available_at=NOW - timedelta(days=2) + timedelta(hours=1),
        recorded_at=NOW - timedelta(days=2) + timedelta(hours=2),
    )
    second_period = observation(
        sequence=2,
        monitoring_policy=monitoring_policy,
        period_start=second_start,
        period_end=second_end,
        observed_at=NOW - timedelta(days=1),
        available_at=NOW - timedelta(days=1) + timedelta(hours=1),
        recorded_at=NOW - timedelta(days=1) + timedelta(hours=2),
    )

    assessment = _evaluate(
        monitoring_policy=monitoring_policy,
        observations=(first_period, second_period),
    )

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert first_period.observation_period_id != second_period.observation_period_id
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_OVERLAP in assessment.blockers


def test_tampered_period_calendar_is_blocked_by_binding_and_content_seal() -> None:
    """A fact cannot rewrite calendar provenance while retaining its old period ID."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(sequence=1, monitoring_policy=monitoring_policy)
    object.__setattr__(fact, "period_calendar_hash", "e" * 64)

    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_MISMATCH in assessment.blockers
    assert R6MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH in assessment.blockers


@pytest.mark.parametrize(
    ("fact_kwargs", "expected_blocker"),
    [
        (
            {"source_owner": "attacker"},
            R6MonitoringBlockerCode.OBSERVATION_OWNER_MISMATCH,
        ),
        (
            {"pit_manifest_id": "substituted-manifest"},
            R6MonitoringBlockerCode.PIT_MANIFEST_MISMATCH,
        ),
        (
            {"pit_manifest_hash": "e" * 64},
            R6MonitoringBlockerCode.PIT_MANIFEST_MISMATCH,
        ),
        (
            {"evidence_ref": "attacker://self-attested"},
            R6MonitoringBlockerCode.EVIDENCE_REF_MISMATCH,
        ),
    ],
)
def test_self_attested_owner_manifest_or_evidence_is_blocked(
    fact_kwargs: dict[str, str],
    expected_blocker: R6MonitoringBlockerCode,
) -> None:
    """Facts must match policy-owned source, PIT manifest, and evidence namespace."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(
        sequence=1,
        monitoring_policy=monitoring_policy,
        **fact_kwargs,
    )
    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert expected_blocker in assessment.blockers


def test_privately_mutated_observation_fails_content_seal_replay() -> None:
    """Frozen-dataclass bypasses cannot keep a stale owner-fact hash healthy."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(sequence=1, monitoring_policy=monitoring_policy)
    object.__setattr__(fact, "evidence_ref", "attacker://mutated-after-seal")

    assessment = _evaluate(monitoring_policy=monitoring_policy, observations=(fact,))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH in assessment.blockers


def test_policy_reaction_diagnostics_are_required_raw_metrics() -> None:
    """Policy diagnostics cannot be replaced by an owner-declared summary."""

    monitoring_policy = policy(minimum_observation_count=1)
    fact = observation(sequence=1, monitoring_policy=monitoring_policy)
    diagnostic_keys = {
        R6MonitoringMetricKey.POLICY_ADJUSTED_R_SQUARED,
        R6MonitoringMetricKey.POLICY_RESIDUAL_AUTOCORRELATION_P_VALUE,
        R6MonitoringMetricKey.POLICY_HETEROSKEDASTICITY_P_VALUE,
        R6MonitoringMetricKey.POLICY_PARAMETER_STABILITY_P_VALUE,
        R6MonitoringMetricKey.POLICY_CONDITION_NUMBER,
    }

    assert diagnostic_keys.issubset({item.metric_key for item in fact.metrics})
