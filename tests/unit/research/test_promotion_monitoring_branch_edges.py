"""Branch-focused public behavior tests for R4 and R5 monitoring evaluators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringAssessment,
    R4MonitoringAssessmentStatus,
    R4MonitoringBlockerCode,
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
    evaluate_r4_promotion_monitoring,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
    R5MonitoringBlockerCode,
    R5MonitoringMetricResult,
    R5PostPromotionMonitoringAssessment,
    evaluate_r5_post_promotion_monitoring,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
    R5MonitoringPolicy,
    R5MonitoringThresholdDirection,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
    monitoring_fact_hash,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)
from tests.unit.research.test_r5_relative_value_monitoring import BASE as R5_BASE
from tests.unit.research.test_r5_relative_value_monitoring import HASH_A as R5_HASH_A
from tests.unit.research.test_r5_relative_value_monitoring import _active as r5_active
from tests.unit.research.test_r5_relative_value_monitoring import _calendar as r5_calendar
from tests.unit.research.test_r5_relative_value_monitoring import _facts as r5_facts
from tests.unit.research.test_r5_relative_value_monitoring import _fixed_income as r5_fixed_income
from tests.unit.research.test_r5_relative_value_monitoring import _policy as r5_policy

R4_UNSET = object()
R5_UNSET = object()


def _r4_case() -> tuple[
    R4PromotionDecision,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
    tuple[R4MonitoringObservation, ...],
]:
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


def _evaluate_r4(
    decision: R4PromotionDecision,
    calendar: R4MonitoringPeriodCalendar,
    policy: R4MonitoringPolicy,
    observations: tuple[R4MonitoringObservation, ...] | list[R4MonitoringObservation],
    *,
    active_decision: R4PromotionDecision | None | object = R4_UNSET,
    portfolio_result: object = R4_UNSET,
    current_r3_attestation: object = R4_UNSET,
    policy_value: R4MonitoringPolicy | None | object = R4_UNSET,
    calendar_value: R4MonitoringPeriodCalendar | None | object = R4_UNSET,
    requested_policy_id: str | object = R4_UNSET,
    requested_policy_version: str | object = R4_UNSET,
    expected_policy_hash: str | object = R4_UNSET,
    evaluated_at: datetime | object = R4_UNSET,
) -> R4MonitoringAssessment:
    selected_active = decision if active_decision is R4_UNSET else active_decision
    selected_portfolio = (
        decision.trial.portfolio_record if portfolio_result is R4_UNSET else portfolio_result
    )
    selected_r3 = (
        decision.trial.current_r3_attestation
        if current_r3_attestation is R4_UNSET
        else current_r3_attestation
    )
    selected_policy = policy if policy_value is R4_UNSET else policy_value
    selected_calendar = calendar if calendar_value is R4_UNSET else calendar_value
    selected_evaluated_at = (
        calendar.valid_from + timedelta(hours=2, minutes=30)
        if evaluated_at is R4_UNSET
        else evaluated_at
    )
    return evaluate_r4_promotion_monitoring(
        requested_active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        requested_policy_id=(
            policy.policy_id if requested_policy_id is R4_UNSET else requested_policy_id
        ),
        requested_policy_version=(
            policy.policy_version
            if requested_policy_version is R4_UNSET
            else requested_policy_version
        ),
        expected_policy_hash=(
            policy.content_hash if expected_policy_hash is R4_UNSET else expected_policy_hash
        ),
        active_decision=selected_active,
        portfolio_result=selected_portfolio,
        current_r3_attestation=selected_r3,
        policy=selected_policy,
        period_calendar=selected_calendar,
        observations=observations,
        evaluated_at=selected_evaluated_at,
    )


def _evaluate_r5(
    policy: R5MonitoringPolicy,
    facts: tuple[R5PostPromotionMonitoringFact, ...] | list[R5PostPromotionMonitoringFact],
    *,
    active: R5MonitoringActiveLifecycle | None | object = R5_UNSET,
    fixed_income: R5MonitoringFixedIncomeEvidence | None | object = R5_UNSET,
    policy_value: object = R5_UNSET,
    calendar_value: R5MonitoringCalendar | None | object = R5_UNSET,
    requested_policy_id: str | object = R5_UNSET,
    requested_policy_version: str | object = R5_UNSET,
    expected_policy_hash: str | object = R5_UNSET,
    evaluated_at: datetime | object = R5_UNSET,
) -> R5PostPromotionMonitoringAssessment:
    selected_active = r5_active() if active is R5_UNSET else active
    selected_fixed_income = r5_fixed_income() if fixed_income is R5_UNSET else fixed_income
    selected_policy = policy if policy_value is R5_UNSET else policy_value
    selected_calendar = r5_calendar() if calendar_value is R5_UNSET else calendar_value
    selected_evaluated_at = (
        R5_BASE + timedelta(days=3, hours=1) if evaluated_at is R5_UNSET else evaluated_at
    )
    return evaluate_r5_post_promotion_monitoring(
        requested_policy_id=(
            policy.policy_id if requested_policy_id is R5_UNSET else requested_policy_id
        ),
        requested_policy_version=(
            policy.policy_version
            if requested_policy_version is R5_UNSET
            else requested_policy_version
        ),
        expected_policy_hash=(
            policy.content_hash if expected_policy_hash is R5_UNSET else expected_policy_hash
        ),
        active_lifecycle=selected_active,
        fixed_income=selected_fixed_income,
        policy=selected_policy,
        calendar=selected_calendar,
        portfolio_facts=facts,
        evaluated_at=selected_evaluated_at,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_exception", "message"),
    (
        pytest.param(
            lambda values: values.update(metric_key="coverage_ratio"),
            TypeError,
            "key is invalid",
            id="metric-key",
        ),
        pytest.param(
            lambda values: values.update(direction="at_least"),
            TypeError,
            "direction is invalid",
            id="direction",
        ),
        pytest.param(
            lambda values: values.update(breached_period_ids=[R5_HASH_A]),
            TypeError,
            "period IDs must be a tuple",
            id="periods-type",
        ),
        pytest.param(
            lambda values: values.update(breached_period_ids=(R5_HASH_A, R5_HASH_A)),
            ValueError,
            "periods must be unique",
            id="periods-duplicate",
        ),
        pytest.param(
            lambda values: values.update(breached_period_ids=("short",)),
            ValueError,
            "must be a lowercase SHA-256 digest",
            id="period-hash",
        ),
        pytest.param(
            lambda values: values.update(trailing_consecutive_breaches=True),
            ValueError,
            "trailing breaches is outside",
            id="trailing-range",
        ),
        pytest.param(
            lambda values: values.update(required_consecutive_breaches=1),
            ValueError,
            "retirement review consecutive breaches is outside",
            id="required-range",
        ),
    ),
)
def test_r5_metric_result_rejects_noncanonical_edge_inputs(
    mutation: Callable[[dict[str, object]], None],
    expected_exception: type[Exception],
    message: str,
) -> None:
    values = {
        "metric_key": R5MonitoringMetricKey.COVERAGE_RATIO,
        "unit": R5MonitoringMetricUnit.RATIO,
        "direction": R5MonitoringThresholdDirection.AT_LEAST,
        "threshold": Decimal("1"),
        "latest_value": Decimal("1"),
        "breached_period_ids": (),
        "trailing_consecutive_breaches": 0,
        "required_consecutive_breaches": 2,
    }
    mutation(values)

    with pytest.raises(expected_exception, match=message):
        R5MonitoringMetricResult(**values)


@pytest.mark.parametrize(
    "case",
    (
        "version",
        "status",
        "collections",
        "duplicate_fact_hash",
        "metric_collection",
        "metric_item",
        "metric_order",
        "blocked_shape",
        "blocker_in_available",
        "manual_flag",
        "automatic_retirement",
        "safety_flag",
    ),
)
def test_r5_assessment_rejects_tampered_shape_and_safety_fields(case: str) -> None:
    policy = r5_policy()
    facts = r5_facts(policy)
    assessment = _evaluate_r5(policy, facts)
    updates: dict[str, object] = {
        "version": {"assessment_version": "unsupported"},
        "status": {"status": "healthy"},
        "collections": {"fact_hashes": list(assessment.fact_hashes)},
        "duplicate_fact_hash": {"fact_hashes": (assessment.fact_hashes[0],) * 2},
        "metric_collection": {"metric_results": list(assessment.metric_results)},
        "metric_item": {"metric_results": (object(), *assessment.metric_results[1:])},
        "metric_order": {"metric_results": tuple(reversed(assessment.metric_results))},
        "blocked_shape": {"status": R5MonitoringAssessmentStatus.BLOCKED},
        "blocker_in_available": {"blocker_codes": (R5MonitoringBlockerCode.POLICY_INACTIVE,)},
        "manual_flag": {"manual_retirement_review_required": True},
        "automatic_retirement": {"automatic_retirement": True},
        "safety_flag": {"research_only": False},
    }

    messages = {
        "version": "version is unsupported",
        "status": "status is invalid",
        "collections": "collections must be tuples",
        "duplicate_fact_hash": "fact hashes must be unique",
        "metric_collection": "collections must be tuples",
        "metric_item": "metric result type is invalid",
        "metric_order": "metrics are non-canonical",
        "blocked_shape": "blocked monitoring assessment shape is invalid",
        "blocker_in_available": "available monitoring assessment shape is invalid",
        "manual_flag": "manual review flag differs",
        "automatic_retirement": "safety boundary differs",
        "safety_flag": "safety boundary differs",
    }

    with pytest.raises((TypeError, ValueError), match=messages[case]):
        replace(assessment, **updates[case])


def test_r5_assessment_replay_requires_exact_public_owner_types() -> None:
    policy = r5_policy()
    calendar = r5_calendar()
    facts = r5_facts(policy)
    assessment = _evaluate_r5(policy, facts)

    with pytest.raises(TypeError, match="replay policy"):
        assessment.validated_copy(policy=object(), calendar=calendar, facts=facts)
    with pytest.raises(TypeError, match="replay calendar"):
        assessment.validated_copy(policy=policy, calendar=object(), facts=facts)
    with pytest.raises(TypeError, match="replay facts"):
        assessment.validated_copy(policy=policy, calendar=calendar, facts=list(facts))


def test_r5_evaluator_blocks_missing_substituted_and_inactive_owners() -> None:
    policy = r5_policy()
    calendar = r5_calendar()
    facts = r5_facts(policy)

    missing_active = _evaluate_r5(policy, facts, active=None)
    assert R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_UNAVAILABLE in missing_active.blocker_codes

    missing_fixed_income = _evaluate_r5(policy, facts, fixed_income=None)
    assert R5MonitoringBlockerCode.FIXED_INCOME_UNAVAILABLE in missing_fixed_income.blocker_codes

    missing_policy = _evaluate_r5(policy, facts, policy_value=None)
    assert R5MonitoringBlockerCode.POLICY_UNAVAILABLE in missing_policy.blocker_codes
    assert R5MonitoringBlockerCode.CALENDAR_SUBSTITUTED in missing_policy.blocker_codes
    assert R5MonitoringBlockerCode.CALENDAR_INCOMPLETE in missing_policy.blocker_codes

    missing_calendar = _evaluate_r5(policy, facts, calendar_value=None)
    assert R5MonitoringBlockerCode.CALENDAR_UNAVAILABLE in missing_calendar.blocker_codes
    assert R5MonitoringBlockerCode.FACT_INCOMPLETE in missing_calendar.blocker_codes

    list_facts = _evaluate_r5(policy, list(facts), calendar_value=calendar)
    assert R5MonitoringBlockerCode.FACT_INCOMPLETE in list_facts.blocker_codes

    substituted_policy = r5_policy(calendar)
    object.__setattr__(substituted_policy, "content_hash", "0" * 64)
    policy_result = _evaluate_r5(
        policy,
        facts,
        policy_value=substituted_policy,
        expected_policy_hash=policy.content_hash,
    )
    assert R5MonitoringBlockerCode.POLICY_SUBSTITUTED in policy_result.blocker_codes

    substituted_active = r5_active()
    object.__setattr__(substituted_active, "content_hash", "0" * 64)
    active_result = _evaluate_r5(policy, facts, active=substituted_active)
    assert R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_SUBSTITUTED in active_result.blocker_codes

    substituted_fixed_income = r5_fixed_income()
    object.__setattr__(substituted_fixed_income, "content_hash", "0" * 64)
    fixed_income_result = _evaluate_r5(policy, facts, fixed_income=substituted_fixed_income)
    assert R5MonitoringBlockerCode.FIXED_INCOME_SUBSTITUTED in fixed_income_result.blocker_codes

    late_fixed_income = replace(
        r5_fixed_income(),
        recorded_at=R5_BASE + timedelta(days=4),
    )
    late_result = _evaluate_r5(policy, facts, fixed_income=late_fixed_income)
    assert R5MonitoringBlockerCode.FIXED_INCOME_SUBSTITUTED in late_result.blocker_codes

    inactive_result = _evaluate_r5(
        policy,
        facts,
        evaluated_at=R5_BASE + timedelta(days=6),
    )
    assert R5MonitoringBlockerCode.POLICY_INACTIVE in inactive_result.blocker_codes
    assert R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_INACTIVE in inactive_result.blocker_codes


def test_r5_facts_require_exact_order_graph_and_freshness() -> None:
    policy = r5_policy()
    facts = r5_facts(policy)

    reordered = _evaluate_r5(policy, (facts[1], facts[0], facts[2]))
    assert R5MonitoringBlockerCode.FACT_INCOMPLETE in reordered.blocker_codes

    wrong_type = _evaluate_r5(policy, (facts[0], object(), facts[2]))
    assert R5MonitoringBlockerCode.FACT_SUBSTITUTED in wrong_type.blocker_codes

    extra_fact = r5_facts(policy)[-1]
    object.__setattr__(extra_fact, "fact_id", "extra-fact")
    object.__setattr__(extra_fact, "content_hash", monitoring_fact_hash(extra_fact))
    extra = _evaluate_r5(policy, (*facts, extra_fact))
    assert R5MonitoringBlockerCode.FACT_INCOMPLETE in extra.blocker_codes
    assert R5MonitoringBlockerCode.FACT_SUBSTITUTED in extra.blocker_codes

    tampered = r5_facts(policy)
    object.__setattr__(tampered[-1], "content_hash", "0" * 64)
    tampered_result = _evaluate_r5(policy, tampered)
    assert R5MonitoringBlockerCode.FACT_SUBSTITUTED in tampered_result.blocker_codes

    graph_substitution = _evaluate_r5(
        policy,
        facts,
        active=replace(r5_active(), decision_id="other-decision"),
    )
    assert R5MonitoringBlockerCode.ACTIVE_LIFECYCLE_SUBSTITUTED in (
        graph_substitution.blocker_codes
    )
    assert R5MonitoringBlockerCode.FACT_SUBSTITUTED in graph_substitution.blocker_codes

    age_result = _evaluate_r5(
        policy,
        facts,
        evaluated_at=R5_BASE + timedelta(days=6),
    )
    assert R5MonitoringBlockerCode.FACT_FUTURE_OR_STALE in age_result.blocker_codes


def test_r4_assessment_rejects_invalid_projection_shape_and_flags() -> None:
    decision, calendar, policy, observations = _r4_case()
    assessment = _evaluate_r4(decision, calendar, policy, observations)
    blocker = R4MonitoringBlockerCode.POLICY_INACTIVE

    invalid_updates = (
        ({"status": "healthy"}, "status is invalid"),
        ({"blockers": [blocker]}, "blockers are invalid"),
        ({"blockers": ("not-a-code",)}, "blockers are invalid"),
        ({"blockers": (blocker, blocker)}, "blockers must be unique"),
        ({"observation_hashes": list(assessment.observation_hashes)}, "hashes must be a tuple"),
        (
            {"observation_hashes": (assessment.observation_hashes[0],) * 2},
            "hashes must be unique",
        ),
        ({"metric_results": list(assessment.metric_results)}, "metric results are invalid"),
        (
            {"metric_results": (object(), *assessment.metric_results[1:])},
            "metric results are invalid",
        ),
        ({"review_reason_codes": ["reason"]}, "reasons must be a tuple"),
        ({"review_reason_codes": ("z", "a")}, "reasons must be canonical and unique"),
        ({"label_drift_detected": 1}, "must be boolean"),
    )
    for update, message in invalid_updates:
        with pytest.raises(ValueError, match=message):
            replace(assessment, **update)

    with pytest.raises(ValueError, match="blocked"):
        replace(assessment, status=R4MonitoringAssessmentStatus.BLOCKED)
    with pytest.raises(ValueError, match="non-blocked"):
        replace(assessment, blockers=(blocker,))

    invalid_key = replace(assessment.metric_results[0], metric_key="invalid")
    with pytest.raises(ValueError, match="metric key"):
        replace(
            assessment,
            metric_results=(invalid_key, *assessment.metric_results[1:]),
        )
    with pytest.raises(ValueError, match="review flag"):
        replace(assessment, retirement_review_required=True)
    with pytest.raises(ValueError, match="status"):
        replace(assessment, status=R4MonitoringAssessmentStatus.BREACHED)
    with pytest.raises(ValueError, match="automatically"):
        replace(assessment, automatic_retirement=True)
    with pytest.raises(ValueError, match="authorize"):
        replace(assessment, research_only=False)


def test_r4_evaluator_fails_closed_for_missing_and_invalid_owner_evidence() -> None:
    decision, calendar, policy, observations = _r4_case()

    missing_active = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        active_decision=None,
    )
    assert R4MonitoringBlockerCode.ACTIVE_DECISION_MISSING in missing_active.blockers

    missing_portfolio = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        portfolio_result=None,
    )
    assert R4MonitoringBlockerCode.PORTFOLIO_RESULT_MISSING in missing_portfolio.blockers

    missing_r3 = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        current_r3_attestation=None,
    )
    assert R4MonitoringBlockerCode.R3_ATTESTATION_MISSING in missing_r3.blockers

    missing_policy = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        policy_value=None,
    )
    assert R4MonitoringBlockerCode.POLICY_MISSING in missing_policy.blockers

    missing_calendar = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        calendar_value=None,
    )
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_MISSING in missing_calendar.blockers

    invalid_decision = monitoring_decision()
    object.__setattr__(invalid_decision, "content_hash", "0" * 64)
    invalid_decision_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        active_decision=invalid_decision,
    )
    assert R4MonitoringBlockerCode.ACTIVE_DECISION_INVALID in invalid_decision_result.blockers

    invalid_portfolio_decision = monitoring_decision()
    object.__setattr__(
        invalid_portfolio_decision.trial.portfolio_record,
        "content_hash",
        "0" * 64,
    )
    invalid_portfolio_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        active_decision=invalid_portfolio_decision,
        portfolio_result=invalid_portfolio_decision.trial.portfolio_record,
    )
    assert R4MonitoringBlockerCode.ACTIVE_DECISION_INVALID in invalid_portfolio_result.blockers
    assert R4MonitoringBlockerCode.PORTFOLIO_RESULT_INVALID in invalid_portfolio_result.blockers

    invalid_r3_decision = monitoring_decision()
    object.__setattr__(
        invalid_r3_decision.trial.current_r3_attestation,
        "content_hash",
        "0" * 64,
    )
    invalid_r3_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        active_decision=invalid_r3_decision,
        current_r3_attestation=invalid_r3_decision.trial.current_r3_attestation,
    )
    assert R4MonitoringBlockerCode.ACTIVE_DECISION_INVALID in invalid_r3_result.blockers
    assert R4MonitoringBlockerCode.R3_ATTESTATION_INVALID in invalid_r3_result.blockers


def test_r4_policy_and_calendar_edges_remain_fail_closed() -> None:
    decision, calendar, policy, observations = _r4_case()

    substituted_policy = monitoring_policy(decision, calendar)
    object.__setattr__(substituted_policy, "thresholds", (object(), *policy.thresholds[1:]))
    policy_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        (),
        policy_value=substituted_policy,
    )
    assert R4MonitoringBlockerCode.POLICY_HASH_MISMATCH in policy_result.blockers

    binding_policy = replace(policy, policy_id="different-policy")
    binding_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        policy_value=binding_policy,
    )
    assert R4MonitoringBlockerCode.POLICY_BINDING_MISMATCH in binding_result.blockers

    future_policy = monitoring_policy(decision, calendar)
    future_evaluated_at = calendar.valid_from + timedelta(hours=2, minutes=30)
    object.__setattr__(
        future_policy,
        "recorded_at",
        future_evaluated_at + timedelta(hours=1),
    )
    future_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        policy_value=future_policy,
        expected_policy_hash=policy.content_hash,
    )
    assert R4MonitoringBlockerCode.POLICY_FROM_FUTURE in future_result.blockers

    causal_policy = monitoring_policy(decision, calendar)
    object.__setattr__(
        causal_policy,
        "recorded_at",
        decision.recorded_at - timedelta(minutes=1),
    )
    causal_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        policy_value=causal_policy,
        requested_policy_id=causal_policy.policy_id,
        requested_policy_version=causal_policy.policy_version,
        expected_policy_hash=causal_policy.content_hash,
    )
    assert R4MonitoringBlockerCode.POLICY_CAUSALITY_INVALID in causal_result.blockers

    inactive_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        evaluated_at=calendar.valid_until + timedelta(minutes=1),
    )
    assert R4MonitoringBlockerCode.POLICY_INACTIVE in inactive_result.blockers
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_INACTIVE in inactive_result.blockers

    malformed_calendar = monitoring_calendar(decision)
    object.__setattr__(malformed_calendar, "entries", (object(),))
    malformed_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        (),
        calendar_value=malformed_calendar,
    )
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH in malformed_result.blockers

    binding_calendar = replace(calendar, source_owner="different-owner")
    binding_calendar_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        calendar_value=binding_calendar,
    )
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_BINDING_MISMATCH in (
        binding_calendar_result.blockers
    )

    future_calendar = monitoring_calendar(decision)
    object.__setattr__(
        future_calendar,
        "recorded_at",
        future_evaluated_at + timedelta(hours=1),
    )
    future_calendar_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        (),
        calendar_value=future_calendar,
    )
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_FROM_FUTURE in future_calendar_result.blockers

    horizon_calendar = monitoring_calendar(decision)
    object.__setattr__(
        horizon_calendar,
        "valid_until",
        calendar.valid_until - timedelta(minutes=1),
    )
    horizon_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        observations,
        calendar_value=horizon_calendar,
    )
    assert R4MonitoringBlockerCode.PERIOD_CALENDAR_HORIZON_INVALID in horizon_result.blockers


def test_r4_observation_collection_edges_and_owner_bindings() -> None:
    decision, calendar, policy, observations = _r4_case()
    first, second = observations

    missing = _evaluate_r4(decision, calendar, policy, ())
    assert R4MonitoringBlockerCode.OBSERVATIONS_MISSING in missing.blockers

    non_tuple = _evaluate_r4(decision, calendar, policy, [first])
    assert R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH in non_tuple.blockers

    sort_error = monitoring_observation(
        period_index=1,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    object.__setattr__(sort_error, "period_start", object())
    sort_result = _evaluate_r4(decision, calendar, policy, (first, sort_error))
    assert R4MonitoringBlockerCode.OBSERVATION_HASH_MISMATCH in sort_result.blockers

    duplicate_result = _evaluate_r4(decision, calendar, policy, (first, first))
    assert R4MonitoringBlockerCode.OBSERVATION_IDENTITY_DUPLICATE in duplicate_result.blockers
    assert R4MonitoringBlockerCode.OBSERVATION_PERIOD_DUPLICATE in duplicate_result.blockers

    period_tamper = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    object.__setattr__(period_tamper, "period_id", "f" * 64)
    period_result = _evaluate_r4(decision, calendar, policy, (period_tamper, second))
    assert R4MonitoringBlockerCode.OBSERVATION_PERIOD_NOT_IN_CALENDAR in period_result.blockers

    owner_cases = (
        (
            replace(first, policy_id="different-policy"),
            R4MonitoringBlockerCode.OBSERVATION_BINDING_MISMATCH,
        ),
        (
            replace(first, source_owner="different-owner"),
            R4MonitoringBlockerCode.OBSERVATION_OWNER_MISMATCH,
        ),
        (
            replace(first, portfolio_record_id="different-record"),
            R4MonitoringBlockerCode.PORTFOLIO_BINDING_MISMATCH,
        ),
        (
            replace(first, r3_attestation_content_hash=R5_HASH_A),
            R4MonitoringBlockerCode.R3_BINDING_MISMATCH,
        ),
        (
            replace(first, pit_manifest_id="different-pit"),
            R4MonitoringBlockerCode.PIT_MANIFEST_MISMATCH,
        ),
        (
            replace(first, pit_manifest_hash=R5_HASH_A),
            R4MonitoringBlockerCode.PIT_MANIFEST_MISMATCH,
        ),
        (
            replace(first, evidence_ref="other:evidence"),
            R4MonitoringBlockerCode.EVIDENCE_REF_MISMATCH,
        ),
        (
            replace(first, label_protocol_version="other-labels"),
            R4MonitoringBlockerCode.LABEL_PROTOCOL_MISMATCH,
        ),
    )
    for observation, blocker in owner_cases:
        result = _evaluate_r4(decision, calendar, policy, (observation, second))
        assert blocker in result.blockers

    future = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    evaluated_at = calendar.valid_from + timedelta(hours=2, minutes=30)
    object.__setattr__(future, "recorded_at", evaluated_at + timedelta(minutes=1))
    future_result = _evaluate_r4(decision, calendar, policy, (future, second))
    assert R4MonitoringBlockerCode.OBSERVATION_FROM_FUTURE in future_result.blockers

    stale = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    object.__setattr__(stale, "valid_until", evaluated_at)
    stale_result = _evaluate_r4(decision, calendar, policy, (stale, second))
    assert R4MonitoringBlockerCode.OBSERVATION_STALE in stale_result.blockers

    duplicate_metric = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    object.__setattr__(
        duplicate_metric,
        "metrics",
        (duplicate_metric.metrics[0], *duplicate_metric.metrics),
    )
    duplicate_metric_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        (duplicate_metric, second),
    )
    assert R4MonitoringBlockerCode.METRIC_DUPLICATE in duplicate_metric_result.blockers

    invalid_domain = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    object.__setattr__(invalid_domain.metrics[0], "value", Decimal("-1"))
    invalid_domain_result = _evaluate_r4(
        decision,
        calendar,
        policy,
        (invalid_domain, second),
    )
    assert R4MonitoringBlockerCode.METRIC_DOMAIN_INVALID in invalid_domain_result.blockers

    policy_skipped = _evaluate_r4(
        decision,
        calendar,
        policy,
        (first,),
        policy_value=None,
    )
    assert R4MonitoringBlockerCode.POLICY_MISSING in policy_skipped.blockers
