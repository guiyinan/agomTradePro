"""Business boundary tests for R4 monitoring evidence and lifecycle safety."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r4_promotion_decision import R4PromotionDecisionOutcome
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleState,
    derive_r4_promotion_lifecycle_state,
)
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringBlockerCode,
    R4MonitoringMetricKey,
    R4MonitoringMetricObservation,
    R4MonitoringPeriodEntry,
    R4MonitoringThreshold,
    R4MonitoringThresholdDirection,
    evaluate_r4_promotion_monitoring,
)
from apps.research.domain.r4_promotion_monitoring_contracts import (
    derive_r4_monitoring_period_id,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)
from tests.unit.research.test_r4_promotion_lifecycle import (
    _promote,
    _rollback,
    _root,
    _second_decision,
)

_DEFAULT_PERIOD_CALENDAR = object()


def _case() -> tuple:
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
    return decision, calendar, policy, observations


def _evaluate(
    decision: object,
    calendar: object,
    policy: object,
    observations: object,
    *,
    active_decision: object | None = None,
    portfolio_result: object | None = None,
    current_r3_attestation: object | None = None,
    period_calendar: object = _DEFAULT_PERIOD_CALENDAR,
    requested_active_decision: R4PromotionDecisionIdentity | None = None,
) -> object:
    selected_decision = decision
    selected_calendar = calendar
    selected_policy = policy
    return evaluate_r4_promotion_monitoring(
        requested_active_decision=(
            R4PromotionDecisionIdentity.from_decision(selected_decision)
            if requested_active_decision is None
            else requested_active_decision
        ),
        requested_policy_id=selected_policy.policy_id,
        requested_policy_version=selected_policy.policy_version,
        expected_policy_hash=selected_policy.content_hash,
        active_decision=(selected_decision if active_decision is None else active_decision),
        portfolio_result=(
            selected_decision.trial.portfolio_record
            if portfolio_result is None
            else portfolio_result
        ),
        current_r3_attestation=(
            selected_decision.trial.current_r3_attestation
            if current_r3_attestation is None
            else current_r3_attestation
        ),
        policy=selected_policy,
        period_calendar=(
            selected_calendar if period_calendar is _DEFAULT_PERIOD_CALENDAR else period_calendar
        ),
        observations=observations,
        evaluated_at=selected_calendar.valid_from + timedelta(hours=2, minutes=30),
    )


def test_valid_monitoring_evaluation_keeps_research_safety_and_drift_review_only() -> None:
    decision, calendar, policy, observations = _case()

    result = _evaluate(decision, calendar, policy, observations)

    assert result.blockers == ()
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_publish_current is True
    assert result.must_not_execute is True


def test_malformed_owner_seals_are_blocked_without_falling_back_to_caller_values() -> None:
    cases = ("decision", "portfolio", "r3")
    for malformed in cases:
        decision, calendar, policy, observations = _case()
        requested_identity = R4PromotionDecisionIdentity.from_decision(decision)
        if malformed == "decision":
            object.__setattr__(decision, "policy", object())
            kwargs = {"active_decision": decision}
        elif malformed == "portfolio":
            kwargs = {"portfolio_result": object()}
        else:
            kwargs = {"current_r3_attestation": object()}

        result = _evaluate(
            decision,
            calendar,
            policy,
            (),
            requested_active_decision=requested_identity,
            **kwargs,
        )

        blocker = (
            R4MonitoringBlockerCode.ACTIVE_DECISION_INVALID
            if malformed == "decision"
            else (
                R4MonitoringBlockerCode.PORTFOLIO_RESULT_INVALID
                if malformed == "portfolio"
                else R4MonitoringBlockerCode.R3_ATTESTATION_INVALID
            )
        )
        assert blocker in result.blockers
        assert R4MonitoringBlockerCode.OBSERVATIONS_MISSING in result.blockers


def test_observation_hash_and_metric_domain_exceptions_fail_closed() -> None:
    decision, calendar, policy, observations = _case()
    malformed_observation = observations[0]
    object.__setattr__(malformed_observation, "period_id", object())

    malformed_hash = _evaluate(
        decision,
        calendar,
        policy,
        (malformed_observation,),
        period_calendar=None,
    )
    assert R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH in malformed_hash.blockers

    decision, calendar, policy, observations = _case()
    object.__setattr__(observations[0].metrics[0], "value", object())
    malformed_metric = _evaluate(decision, calendar, policy, observations)
    assert R4MonitoringBlockerCode.METRIC_DOMAIN_INVALID in malformed_metric.blockers

    decision, calendar, policy, observations = _case()
    object.__setattr__(observations[0].metrics[0], "metric_key", "unknown-metric")
    missing_threshold = _evaluate(decision, calendar, policy, observations)
    assert R4MonitoringBlockerCode.METRIC_MISSING in missing_threshold.blockers


def test_calendar_contract_rejects_missing_duplicate_gapped_and_unsealed_members() -> None:
    _, calendar, _, _ = _case()
    entries = calendar.entries

    with pytest.raises(ValueError, match="entries are required"):
        replace(calendar, entries=())
    with pytest.raises(ValueError, match="period IDs must be unique"):
        replace(calendar, entries=(entries[0], entries[0]))

    noncanonical = replace(entries[0], period_id="a" * 64)
    with pytest.raises(ValueError, match="identity is not canonical"):
        replace(calendar, entries=(noncanonical, *entries[1:]))

    outside_start = calendar.valid_from - timedelta(hours=1)
    outside = R4MonitoringPeriodEntry(
        period_id=derive_r4_monitoring_period_id(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            period_start=outside_start,
            period_end=calendar.valid_from,
        ),
        period_start=outside_start,
        period_end=calendar.valid_from,
    )
    with pytest.raises(ValueError, match="lies outside validity"):
        replace(calendar, entries=(outside, *entries[1:]))

    with pytest.raises(ValueError, match="periods must be contiguous"):
        replace(calendar, entries=(entries[0], entries[2], entries[3]))
    with pytest.raises(ValueError, match="cover its full validity"):
        replace(calendar, entries=entries[:3])
    with pytest.raises(ValueError, match="calendar clocks are invalid"):
        replace(calendar, valid_from=calendar.recorded_at - timedelta(microseconds=1))

    with pytest.raises(ValueError, match="period must be non-empty"):
        R4MonitoringPeriodEntry(
            period_id="a" * 64,
            period_start=calendar.valid_from,
            period_end=calendar.valid_from,
        )


def test_policy_and_metric_contracts_reject_unbound_or_invalid_configuration() -> None:
    decision, calendar, policy, _ = _case()

    with pytest.raises(ValueError, match="thresholds must be a tuple"):
        replace(policy, thresholds=list(policy.thresholds))
    with pytest.raises(ValueError, match="threshold type is invalid"):
        replace(policy, thresholds=(object(), *policy.thresholds[1:]))
    with pytest.raises(ValueError, match="every threshold exactly once"):
        replace(policy, thresholds=(policy.thresholds[0], *policy.thresholds[:-1]))
    with pytest.raises(ValueError, match="minimum observation count"):
        replace(policy, minimum_observation_count=0)
    with pytest.raises(ValueError, match="maximum observation age"):
        replace(policy, maximum_observation_age_seconds=0)

    rejected_identity = replace(
        policy.active_decision,
        outcome=R4PromotionDecisionOutcome.REJECTED,
    )
    with pytest.raises(ValueError, match="requires an approved decision"):
        replace(policy, active_decision=rejected_identity)
    with pytest.raises(ValueError, match="bind the active R3 seal"):
        replace(policy, expected_label_set_hash="f" * 64)

    with pytest.raises(ValueError, match="metric key is invalid"):
        R4MonitoringMetricObservation(
            metric_key="unknown",
            unit="ratio",
            value=Decimal("0"),
        )
    with pytest.raises(ValueError, match="direction is invalid"):
        R4MonitoringThreshold(
            metric_key=R4MonitoringMetricKey.RELATIVE_NET_RETURN,
            unit="ratio",
            direction="unknown",
            breach_threshold=Decimal("0"),
            retirement_review_consecutive_breaches=2,
        )
    with pytest.raises(ValueError, match="count must be positive"):
        replace(policy.thresholds[0], retirement_review_consecutive_breaches=0)


def test_low_level_contract_guards_reject_bad_token_hash_clock_and_period() -> None:
    _, calendar, _, _ = _case()

    with pytest.raises(ValueError, match="bounded non-blank token"):
        R4MonitoringMetricObservation(
            metric_key=R4MonitoringMetricKey.RELATIVE_NET_RETURN,
            unit=" ",
            value=Decimal("0"),
        )
    with pytest.raises(ValueError, match="SHA-256 digest"):
        R4MonitoringPeriodEntry(
            period_id="not-a-digest",
            period_start=calendar.valid_from,
            period_end=calendar.valid_from + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        R4MonitoringPeriodEntry(
            period_id="a" * 64,
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 2),
        )
    with pytest.raises(ValueError, match="period must be non-empty"):
        derive_r4_monitoring_period_id(
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            period_start=calendar.valid_from,
            period_end=calendar.valid_from,
        )


def test_threshold_restore_revalidation_rejects_invalid_key_and_changed_value() -> None:
    _, _, policy, _ = _case()

    with pytest.raises(ValueError, match="threshold metric_key is invalid"):
        R4MonitoringThreshold(
            metric_key="unknown",
            unit="ratio",
            direction=R4MonitoringThresholdDirection.AT_LEAST,
            breach_threshold=Decimal("0"),
            retirement_review_consecutive_breaches=2,
        )

    class _NonEqualText(str):
        def __eq__(self, other: object) -> bool:
            return False

        def __ne__(self, other: object) -> bool:
            return True

    altered_threshold = policy.thresholds[0]
    object.__setattr__(altered_threshold, "unit", _NonEqualText(altered_threshold.unit))
    with pytest.raises(ValueError, match="validation changed its value"):
        policy.validated_copy()


def test_policy_rejects_a_restored_threshold_tuple_that_cannot_round_trip() -> None:
    _, _, policy, _ = _case()

    class _NonEqualThresholds(tuple):
        def __eq__(self, other: object) -> bool:
            return False

        def __ne__(self, other: object) -> bool:
            return True

    object.__setattr__(policy, "thresholds", _NonEqualThresholds(policy.thresholds))
    with pytest.raises(ValueError, match="thresholds failed validation"):
        policy.__post_init__()


def test_observation_contract_rejects_future_clock_identity_and_decision_flags() -> None:
    decision, calendar, policy, observations = _case()
    observation = observations[0]

    with pytest.raises(ValueError, match="observation clocks are invalid"):
        replace(observation, period_end=observation.period_start)
    with pytest.raises(ValueError, match="period identity is not canonical"):
        replace(observation, period_id="a" * 64)
    with pytest.raises(ValueError, match="cannot authorize production behavior"):
        replace(observation, research_only=False)
    with pytest.raises(ValueError, match="bounded non-blank text"):
        replace(observation, evidence_ref=" ")

    result = _evaluate(
        decision,
        calendar,
        policy,
        (observation,),
    )
    assert result.blockers


def test_r4_monitoring_never_turns_breach_or_revoke_like_input_into_automatic_action() -> None:
    decision, calendar, policy, observations = _case()
    degraded = replace(
        observations[1],
        metrics=tuple(
            replace(
                metric,
                value=(
                    Decimal("-0.10")
                    if metric.metric_key is R4MonitoringMetricKey.RELATIVE_NET_RETURN
                    else metric.value
                ),
            )
            for metric in observations[1].metrics
        ),
    )
    object.__setattr__(degraded, "content_hash", observations[1].content_hash)
    result = _evaluate(decision, calendar, policy, (observations[0], degraded))

    assert result.automatic_retirement is False
    assert result.must_not_publish_current is True
    assert result.must_not_execute is True
    assert result.status.value in {"blocked", "retirement_review_required"}


def test_rollback_requires_exact_head_target_and_preserves_research_lifecycle_state() -> None:
    first = monitoring_decision()
    root = _root(first)
    second = _second_decision()
    promoted = _promote((root,), second, suffix="monitoring-boundary")

    rolled_back = _rollback(
        (root, promoted),
        second,
        first,
        suffix="monitoring-boundary-valid",
    )
    snapshot = derive_r4_promotion_lifecycle_state(
        (root, promoted, rolled_back),
        evaluated_at=rolled_back.recorded_at,
    )
    assert snapshot.state is R4PromotionLifecycleState.ROLLED_BACK
    assert snapshot.active_decision == root.decision

    with pytest.raises(ValueError, match=r"exactly stack\[-2\]"):
        _rollback(
            (root, promoted),
            second,
            second,
            suffix="monitoring-boundary-wrong-target",
        )

    object.__setattr__(promoted, "previous_event_hash", "0" * 64)
    with pytest.raises(ValueError, match="chain is discontinuous"):
        derive_r4_promotion_lifecycle_state(
            (root, promoted),
            evaluated_at=promoted.recorded_at,
        )
