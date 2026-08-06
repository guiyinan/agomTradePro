"""True OOS observation and exact owner-record coverage for R5 trials."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
    R5RelativeValuePromotionTrialState,
    R5RelativeValueTrialObservation,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_observations,
    make_policy,
    make_trial,
)


def test_trial_binds_exact_persisted_results_and_realized_outcome_clocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete trial contains distinct formation records and later outcomes."""

    trial = make_trial(monkeypatch)

    assert trial.state is R5RelativeValuePromotionTrialState.READY_FOR_POLICY_EVALUATION
    assert trial.observed_count == 2
    assert trial.expected_count == 2
    assert trial.coverage_ratio == 1
    assert trial.trial_id == f"r5-rv-trial:{trial.content_hash}"
    assert len({item.fixed_income_record.result_id for item in trial.observations}) == 2
    assert all(
        item.fixed_income_record.recorded_at
        <= item.selection_as_of
        < item.outcome_observed_at
        <= item.outcome_available_at
        <= item.recorded_at
        < item.valid_until
        for item in trial.observations
    )


def test_policy_must_be_preregistered_before_every_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A policy recorded after selection cannot govern the selected trial."""

    policy = make_policy(recorded_at_offset_minutes=5)
    with pytest.raises(ValueError, match="preregistered"):
        R5RelativeValuePromotionTrial.create(
            policy=policy,
            observations=make_observations(monkeypatch),
            evaluated_at=BASE_TIME + timedelta(hours=3),
        )


def test_missing_expected_observation_is_auditable_blocked_not_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coverage never fabricates an absent outcome or zero-hash placeholder."""

    policy = make_policy()
    observation = make_observations(monkeypatch)[0]
    trial = R5RelativeValuePromotionTrial.create(
        policy=policy,
        observations=(observation,),
        evaluated_at=BASE_TIME + timedelta(hours=3),
    )

    assert trial.state is R5RelativeValuePromotionTrialState.BLOCKED
    assert "expected_observation_coverage_incomplete" in trial.blocker_codes
    assert trial.observed_count == 1
    assert trial.coverage_ratio == pytest.approx(0.5)


def test_trial_rejects_record_reuse_and_outcome_rebinding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One exact signal cannot be counted twice or rebound to another outcome."""

    first, second = make_observations(monkeypatch)
    outcome = R5PortfolioOutcomeSeal.create(
        outcome_version=second.outcome_version,
        owner_record_id=second.portfolio_outcome.owner_record_id,
        owner_record_version=second.portfolio_outcome.owner_record_version,
        owner_record_hash=second.portfolio_outcome.owner_record_hash,
        observation_id=second.observation_id,
        fixed_income_result_id=first.fixed_income_record.result_id,
        fixed_income_result_version=first.fixed_income_record.result_version,
        fixed_income_result_record_hash=first.fixed_income_record.result_record_hash,
        fixed_income_owner_seal_hash=first.fixed_income_record.content_hash,
        selection_as_of=second.selection_as_of,
        outcome_observed_at=second.outcome_observed_at,
        outcome_available_at=second.outcome_available_at,
        recorded_at=second.recorded_at,
        valid_until=second.valid_until,
        target_gross_return=second.target_gross_return,
        target_cost=second.target_cost,
        benchmark_gross_return=second.benchmark_gross_return,
        benchmark_cost=second.benchmark_cost,
        target_maximum_drawdown=second.target_maximum_drawdown,
        benchmark_maximum_drawdown=second.benchmark_maximum_drawdown,
        capacity_utilization=second.capacity_utilization,
        liquidity_breached=second.liquidity_breached,
        realized_credit_loss=second.realized_credit_loss,
    )
    rebound = R5RelativeValueTrialObservation.create(
        observation_id=second.observation_id,
        fixed_income_record=first.fixed_income_record,
        portfolio_outcome=outcome,
    )
    with pytest.raises(ValueError, match="distinct fixed-income records"):
        R5RelativeValuePromotionTrial.create(
            policy=make_policy(),
            observations=(first, rebound),
            evaluated_at=BASE_TIME + timedelta(hours=3),
        )
    with pytest.raises(ValueError, match="content hash"):
        replace(
            first.portfolio_outcome,
            target_gross_return=first.target_gross_return + 1,
        )


def test_trial_rejects_one_portfolio_record_reinterpreted_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One canonical Portfolio record cannot count as two realized outcomes."""

    first, second = make_observations(monkeypatch)
    source = second.portfolio_outcome
    duplicate_owner_record = R5PortfolioOutcomeSeal.create(
        outcome_version=source.outcome_version,
        owner_record_id=first.portfolio_outcome.owner_record_id,
        owner_record_version=first.portfolio_outcome.owner_record_version,
        owner_record_hash=first.portfolio_outcome.owner_record_hash,
        observation_id=second.observation_id,
        fixed_income_result_id=second.fixed_income_record.result_id,
        fixed_income_result_version=second.fixed_income_record.result_version,
        fixed_income_result_record_hash=second.fixed_income_record.result_record_hash,
        fixed_income_owner_seal_hash=second.fixed_income_record.content_hash,
        selection_as_of=source.selection_as_of,
        outcome_observed_at=source.outcome_observed_at,
        outcome_available_at=source.outcome_available_at,
        recorded_at=source.recorded_at,
        valid_until=source.valid_until,
        target_gross_return=source.target_gross_return + 1,
        target_cost=source.target_cost,
        benchmark_gross_return=source.benchmark_gross_return,
        benchmark_cost=source.benchmark_cost,
        target_maximum_drawdown=source.target_maximum_drawdown,
        benchmark_maximum_drawdown=source.benchmark_maximum_drawdown,
        capacity_utilization=source.capacity_utilization,
        liquidity_breached=source.liquidity_breached,
        realized_credit_loss=source.realized_credit_loss,
    )
    second_reinterpreted = R5RelativeValueTrialObservation.create(
        observation_id=second.observation_id,
        fixed_income_record=second.fixed_income_record,
        portfolio_outcome=duplicate_owner_record,
    )

    with pytest.raises(ValueError, match="distinct Portfolio outcome records"):
        R5RelativeValuePromotionTrial.create(
            policy=make_policy(),
            observations=(first, second_reinterpreted),
            evaluated_at=BASE_TIME + timedelta(hours=3),
        )
