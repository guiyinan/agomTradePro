"""Synthetic contract tests for R5 post-promotion monitoring Phase A."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from inspect import signature

import pytest

from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
    R5MonitoringMetricResult,
    evaluate_r5_post_promotion_monitoring,
    monitoring_assessment_hash,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringMetric,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
    R5MonitoringPeriodEntry,
    R5MonitoringPolicy,
    R5MonitoringTarget,
    R5MonitoringThreshold,
    R5MonitoringThresholdDirection,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
)

BASE = datetime(2026, 7, 1, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def _ref(
    role: R5MonitoringOwnerRole,
    owner: str,
    identity: str,
    version: str,
    digest: str,
    *,
    known_at: datetime = BASE - timedelta(days=5),
    recorded_at: datetime = BASE - timedelta(days=4),
    valid_until: datetime = BASE + timedelta(days=10),
) -> R5MonitoringOwnerRef:
    return R5MonitoringOwnerRef(
        role=role,
        owner=owner,
        owner_id=identity,
        owner_version=version,
        content_hash=digest,
        known_at=known_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _calendar() -> R5MonitoringCalendar:
    owner = _ref(
        R5MonitoringOwnerRole.CALENDAR,
        "research",
        "r5-calendar",
        "calendar-v1",
        HASH_A,
        known_at=BASE - timedelta(days=3),
        recorded_at=BASE - timedelta(days=2),
        valid_until=BASE + timedelta(days=5),
    )
    entries = tuple(
        R5MonitoringPeriodEntry.create(
            calendar_id=owner.owner_id,
            calendar_version=owner.owner_version,
            period_start=BASE + timedelta(days=index),
            period_end=BASE + timedelta(days=index + 1),
        )
        for index in range(3)
    )
    return R5MonitoringCalendar.create(
        owner=owner,
        entries=entries,
        recorded_at=BASE - timedelta(days=2),
        valid_until=BASE + timedelta(days=5),
    )


def _active() -> R5MonitoringActiveLifecycle:
    return R5MonitoringActiveLifecycle.create(
        scope_id="r5-scope",
        scope_hash=HASH_A,
        decision_id="r5-decision",
        decision_version="decision-v1",
        decision_hash=HASH_B,
        trial_id="r5-trial",
        trial_hash=HASH_C,
        fixed_income_owner_seal_hashes=(HASH_D,),
        stream_id="r5-stream",
        latest_event_id="r5-event",
        latest_event_hash=HASH_E,
        promoted_at=BASE - timedelta(days=3),
        recorded_at=BASE - timedelta(days=3) + timedelta(minutes=1),
        valid_until=BASE + timedelta(days=6),
    )


def _fixed_income() -> R5MonitoringFixedIncomeEvidence:
    return R5MonitoringFixedIncomeEvidence.create(
        result_id="fi-result",
        result_version="result-v1",
        result_hash=HASH_F,
        owner_seal_id="fi-owner-seal",
        owner_seal_version="owner-seal-v1",
        owner_seal_hash=HASH_D,
        recorded_at=BASE - timedelta(days=4),
    )


def _target() -> R5MonitoringTarget:
    return R5MonitoringTarget.create(
        active_lifecycle=_active(),
        fixed_income=_fixed_income(),
        benchmark=_ref(
            R5MonitoringOwnerRole.BENCHMARK,
            "research",
            "r5-benchmark",
            "benchmark-v1",
            HASH_A,
        ),
        cost_policy=_ref(
            R5MonitoringOwnerRole.COST_POLICY,
            "portfolio",
            "r5-cost",
            "cost-v1",
            HASH_B,
        ),
        liquidity_policy=_ref(
            R5MonitoringOwnerRole.LIQUIDITY_POLICY,
            "portfolio",
            "r5-liquidity",
            "liquidity-v1",
            HASH_C,
        ),
        label_baseline=_ref(
            R5MonitoringOwnerRole.LABEL_BASELINE,
            "research",
            "r5-labels",
            "labels-v1",
            HASH_D,
        ),
        data_schema=_ref(
            R5MonitoringOwnerRole.DATA_SCHEMA,
            "fixed_income",
            "r5-data-schema",
            "schema-v1",
            HASH_E,
        ),
    )


def _thresholds() -> tuple[R5MonitoringThreshold, ...]:
    values = {
        R5MonitoringMetricKey.COVERAGE_RATIO: Decimal("1"),
        R5MonitoringMetricKey.EXCESS_NET_RETURN: Decimal("0"),
        R5MonitoringMetricKey.DRAWDOWN_INCREASE: Decimal("0.03"),
        R5MonitoringMetricKey.TOTAL_TARGET_COST: Decimal("0.02"),
        R5MonitoringMetricKey.LIQUIDITY_BREACH: Decimal("0"),
        R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION: Decimal("0.9"),
        R5MonitoringMetricKey.REALIZED_CREDIT_LOSS: Decimal("0.01"),
    }
    return tuple(
        R5MonitoringThreshold.canonical(
            metric_key=key,
            breach_threshold=values[key],
            retirement_review_consecutive_breaches=2,
        )
        for key in R5MonitoringMetricKey
    )


def _policy(calendar: R5MonitoringCalendar | None = None) -> R5MonitoringPolicy:
    actual_calendar = calendar or _calendar()
    return R5MonitoringPolicy.create(
        policy_scope_id="r5-post-promotion-monitoring",
        target=_target(),
        calendar=actual_calendar,
        thresholds=_thresholds(),
        minimum_complete_periods=3,
        maximum_period_age_seconds=3 * 24 * 60 * 60,
        maximum_source_delay_seconds=2 * 60 * 60,
        recorded_at=BASE - timedelta(days=1),
        valid_until=BASE + timedelta(days=5),
    )


def _source_projection(
    period_end: datetime,
    *,
    identity: str,
    target_cost: Decimal = Decimal("0.01"),
) -> R5MonitoringPortfolioSourceProjection:
    return R5MonitoringPortfolioSourceProjection.create(
        owner_record=_ref(
            R5MonitoringOwnerRole.PORTFOLIO_MONITORING_SOURCE,
            "portfolio",
            identity,
            "record-v1",
            HASH_F,
            known_at=period_end + timedelta(minutes=1),
            recorded_at=period_end + timedelta(minutes=2),
            valid_until=BASE + timedelta(days=5),
        ),
        source_observed_at=period_end - timedelta(minutes=1),
        coverage_observed_count=10,
        coverage_expected_count=10,
        target_gross_return=target_cost + Decimal("0.015"),
        benchmark_gross_return=Decimal("0.01"),
        target_execution_cost=target_cost,
        target_financing_cost=Decimal("0"),
        target_liquidity_cost=Decimal("0"),
        benchmark_execution_cost=Decimal("0.005"),
        benchmark_financing_cost=Decimal("0"),
        benchmark_liquidity_cost=Decimal("0"),
        target_drawdown=Decimal("0.03"),
        benchmark_drawdown=Decimal("0.02"),
        liquidity_breach_count=0,
        liquidity_eligible_count=10,
        capacity_used=Decimal("7"),
        capacity_limit=Decimal("10"),
        realized_credit_loss=Decimal("0.001"),
        credit_exposure=Decimal("1"),
    )


def _facts(
    policy: R5MonitoringPolicy,
    *,
    breached_indexes: tuple[int, ...] = (),
    label_drift_indexes: tuple[int, ...] = (),
    delayed_indexes: tuple[int, ...] = (),
) -> tuple[R5PostPromotionMonitoringFact, ...]:
    calendar = _calendar()
    facts: list[R5PostPromotionMonitoringFact] = []
    for index, period in enumerate(calendar.entries):
        observed_at = period.period_end + (
            timedelta(hours=3) if index in delayed_indexes else timedelta(minutes=5)
        )
        facts.append(
            R5PostPromotionMonitoringFact.create(
                fact_id=f"portfolio-monitoring-{index}",
                fact_version="fact-v1",
                period=period,
                calendar=calendar,
                target=policy.target,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_hash=policy.content_hash,
                source_projection=_source_projection(
                    period.period_end,
                    identity=f"portfolio-record-{index}",
                    target_cost=(Decimal("0.03") if index in breached_indexes else Decimal("0.01")),
                ),
                observed_at=observed_at,
                available_at=observed_at + timedelta(minutes=5),
                recorded_at=observed_at + timedelta(minutes=10),
                valid_until=BASE + timedelta(days=5),
                observed_label_hash=(HASH_A if index in label_drift_indexes else HASH_D),
                observed_data_schema_hash=HASH_E,
            )
        )
    return tuple(facts)


def _evaluate(
    policy: R5MonitoringPolicy,
    facts: tuple[R5PostPromotionMonitoringFact, ...],
):
    return evaluate_r5_post_promotion_monitoring(
        requested_policy_id=policy.policy_id,
        requested_policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        active_lifecycle=_active(),
        fixed_income=_fixed_income(),
        policy=policy,
        calendar=_calendar(),
        portfolio_facts=facts,
        evaluated_at=BASE + timedelta(days=3, hours=1),
    )


def test_seven_metric_contract_and_safety_boundary() -> None:
    policy = _policy()
    assessment = _evaluate(policy, _facts(policy))

    assert tuple(item.metric_key for item in assessment.metric_results) == tuple(
        R5MonitoringMetricKey
    )
    assert assessment.status is R5MonitoringAssessmentStatus.HEALTHY
    assert assessment.automatic_retirement is False
    assert assessment.research_only is True
    assert assessment.must_not_publish_current is True
    assert assessment.must_not_decide is True
    assert assessment.must_not_execute is True


def test_fact_accepts_only_raw_projection_and_derives_all_seven_metrics() -> None:
    policy = _policy()
    fact = _facts(policy)[0]

    assert "metrics" not in signature(R5PostPromotionMonitoringFact.create).parameters
    assert tuple((item.metric_key, item.value) for item in fact.metrics) == (
        (R5MonitoringMetricKey.COVERAGE_RATIO, Decimal("1")),
        (R5MonitoringMetricKey.EXCESS_NET_RETURN, Decimal("0.01")),
        (R5MonitoringMetricKey.DRAWDOWN_INCREASE, Decimal("0.01")),
        (R5MonitoringMetricKey.TOTAL_TARGET_COST, Decimal("0.01")),
        (R5MonitoringMetricKey.LIQUIDITY_BREACH, Decimal("0")),
        (R5MonitoringMetricKey.PEAK_CAPACITY_UTILIZATION, Decimal("0.7")),
        (R5MonitoringMetricKey.REALIZED_CREDIT_LOSS, Decimal("0.001")),
    )
    assert fact.source_projection.coverage_observed_count == 10
    assert fact.source_projection.coverage_expected_count == 10

    tampered = deepcopy(fact.source_projection)
    object.__setattr__(tampered, "coverage_expected_count", 11)
    with pytest.raises(ValueError, match="source projection"):
        R5PostPromotionMonitoringFact.create(
            fact_id="tampered-fact",
            fact_version="fact-v1",
            period=_calendar().entries[0],
            calendar=_calendar(),
            target=policy.target,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_hash=policy.content_hash,
            source_projection=tampered,
            observed_at=BASE + timedelta(days=1, minutes=5),
            available_at=BASE + timedelta(days=1, minutes=10),
            recorded_at=BASE + timedelta(days=1, minutes=15),
            valid_until=BASE + timedelta(days=5),
            observed_label_hash=HASH_D,
            observed_data_schema_hash=HASH_E,
        )


def test_raw_denominators_and_owner_role_clocks_are_governed() -> None:
    period_end = BASE + timedelta(days=1)
    source = _source_projection(period_end, identity="raw-denominator")
    with pytest.raises(ValueError, match="coverage"):
        R5MonitoringPortfolioSourceProjection.create(
            **{
                item.name: getattr(source, item.name)
                for item in fields(source)
                if item.name not in {"content_hash", "coverage_expected_count"}
            },
            coverage_expected_count=0,
        )

    with pytest.raises(ValueError, match="canonical owner"):
        _ref(
            R5MonitoringOwnerRole.BENCHMARK,
            "portfolio",
            "wrong-benchmark-owner",
            "v1",
            HASH_A,
        )
    with pytest.raises(ValueError, match="clocks"):
        _ref(
            R5MonitoringOwnerRole.COST_POLICY,
            "portfolio",
            "bad-clock",
            "v1",
            HASH_A,
            known_at=BASE,
            recorded_at=BASE - timedelta(seconds=1),
        )

    target = _target()
    late_benchmark = _ref(
        R5MonitoringOwnerRole.BENCHMARK,
        "research",
        "late-benchmark",
        "v1",
        HASH_A,
        known_at=target.active_lifecycle.promoted_at,
        recorded_at=target.active_lifecycle.promoted_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="active decision"):
        R5MonitoringTarget.create(
            active_lifecycle=target.active_lifecycle,
            fixed_income=target.fixed_income,
            benchmark=late_benchmark,
            cost_policy=target.cost_policy,
            liquidity_policy=target.liquidity_policy,
            label_baseline=target.label_baseline,
            data_schema=target.data_schema,
        )


def test_metric_result_and_assessment_full_replay_reject_substitution() -> None:
    with pytest.raises(ValueError, match="unit"):
        R5MonitoringMetricResult(
            metric_key=R5MonitoringMetricKey.COVERAGE_RATIO,
            unit=R5MonitoringMetricUnit.COST_RATE,
            direction=R5MonitoringThresholdDirection.AT_LEAST,
            threshold=Decimal("1"),
            latest_value=Decimal("1"),
            breached_period_ids=(),
            trailing_consecutive_breaches=0,
            required_consecutive_breaches=2,
        )

    calendar = _calendar()
    policy = _policy(calendar)
    facts = _facts(policy)
    assessment = _evaluate(policy, facts)
    object.__setattr__(assessment.metric_results[0], "latest_value", Decimal("0.5"))
    object.__setattr__(assessment, "content_hash", monitoring_assessment_hash(assessment))
    object.__setattr__(
        assessment,
        "assessment_id",
        f"r5-monitoring-assessment:{assessment.content_hash[:24]}",
    )
    with pytest.raises(ValueError, match="replay"):
        assessment.validated_copy(policy=policy, calendar=calendar, facts=facts)


def test_latest_breach_and_consecutive_or_historical_drift_have_distinct_states() -> None:
    policy = _policy()
    breached = _evaluate(policy, _facts(policy, breached_indexes=(2,)))
    review = _evaluate(policy, _facts(policy, breached_indexes=(1, 2)))
    recovered = _evaluate(policy, _facts(policy, breached_indexes=(0,)))
    drift = _evaluate(policy, _facts(policy, label_drift_indexes=(0,)))

    assert breached.status is R5MonitoringAssessmentStatus.BREACHED
    assert review.status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert recovered.status is R5MonitoringAssessmentStatus.HEALTHY
    assert drift.status is R5MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED


def test_missing_replaced_or_stale_owner_fact_blocks() -> None:
    policy = _policy()
    facts = _facts(policy)
    assert _evaluate(policy, facts[:-1]).status is R5MonitoringAssessmentStatus.BLOCKED

    replaced = deepcopy(facts[-1])
    object.__setattr__(replaced, "benchmark_hash", HASH_F)
    assert _evaluate(policy, (*facts[:-1], replaced)).status is R5MonitoringAssessmentStatus.BLOCKED

    delayed = _facts(policy, delayed_indexes=(2,))
    assert _evaluate(policy, delayed).status is R5MonitoringAssessmentStatus.BLOCKED


@pytest.mark.parametrize(
    ("metric_key", "unit", "value", "direction"),
    (
        (
            R5MonitoringMetricKey.COVERAGE_RATIO,
            R5MonitoringMetricUnit.RATIO,
            Decimal("1.01"),
            R5MonitoringThresholdDirection.AT_LEAST,
        ),
        (
            R5MonitoringMetricKey.LIQUIDITY_BREACH,
            R5MonitoringMetricUnit.BINARY,
            Decimal("0.5"),
            R5MonitoringThresholdDirection.AT_MOST,
        ),
        (
            R5MonitoringMetricKey.EXCESS_NET_RETURN,
            R5MonitoringMetricUnit.RETURN_RATE,
            Decimal("0"),
            R5MonitoringThresholdDirection.AT_MOST,
        ),
    ),
)
def test_metric_domain_unit_and_direction_are_canonical(
    metric_key: R5MonitoringMetricKey,
    unit: R5MonitoringMetricUnit,
    value: Decimal,
    direction: R5MonitoringThresholdDirection,
) -> None:
    if metric_key is R5MonitoringMetricKey.EXCESS_NET_RETURN:
        R5MonitoringMetric(metric_key=metric_key, unit=unit, value=value)
    else:
        with pytest.raises(ValueError):
            R5MonitoringMetric(metric_key=metric_key, unit=unit, value=value)
    with pytest.raises(ValueError):
        R5MonitoringThreshold(
            metric_key=metric_key,
            unit=unit,
            direction=direction,
            breach_threshold=value,
            retirement_review_consecutive_breaches=2,
        )
