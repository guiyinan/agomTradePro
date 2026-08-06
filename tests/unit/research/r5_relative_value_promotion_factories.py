"""Reusable factories for R5 relative-value promotion unit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
    R5RelativeValuePersistenceDraft,
)
from apps.research.application.r5_relative_value_promotion_projection import (
    project_r5_relative_value_owner_record,
)
from apps.research.domain.r5_relative_value_portfolio_outcome import (
    R5PortfolioOutcomeSeal,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
    create_r5_relative_value_promotion_decision,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
    R5RelativeValuePromotionRegistration,
    R5RelativeValuePromotionScope,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
    R5RelativeValueTrialObservation,
)
from tests.unit.fixed_income.test_relative_value_use_case import (
    _EVALUATED_AT,
    _command,
    _fixture_graph,
    _runner_graph,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
BASE_TIME = _EVALUATED_AT


def make_persisted_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[R5PersistedRelativeValueBundle, R5PersistedRelativeValueBundle]:
    """Build two distinct canonical fixed-income owner records."""

    graph = _fixture_graph(monkeypatch)
    runner = _runner_graph(graph).runner
    bundles: list[R5PersistedRelativeValueBundle] = []
    for suffix, minute in (("a", 1), ("b", 2)):
        command = replace(_command(graph), assessment_id=f"r5-assessment-{suffix}")
        run = runner.execute_authoritative(command)
        draft = R5RelativeValuePersistenceDraft.from_authoritative_run(run)
        bundles.append(
            R5PersistedRelativeValueBundle.from_draft(
                draft,
                recorded_at=BASE_TIME + timedelta(minutes=minute),
            )
        )
    return bundles[0], bundles[1]


def make_scope() -> R5RelativeValuePromotionScope:
    """Create one stable semantic R5 stream."""

    return R5RelativeValuePromotionScope.create(
        study_family_id="r5-rv-family",
        currency="CNY",
        universe_policy_id="cn-bond-universe",
        split_policy_id="walk-forward-split",
        cost_policy_id="all-in-cost",
        liquidity_policy_id="tradable-capacity",
    )


def make_policy(
    *,
    scope: R5RelativeValuePromotionScope | None = None,
    expected_observation_ids: tuple[str, ...] = ("obs-a", "obs-b"),
    recorded_at_offset_minutes: int = -20,
    minimum_excess_net_return: Decimal = Decimal("0.001"),
) -> R5RelativeValuePromotionPolicy:
    """Create one explicit pre-selection Research policy."""

    actual_scope = scope or make_scope()
    registration = R5RelativeValuePromotionRegistration.create(
        scope=actual_scope,
        trial_version="trial-v1",
        expected_observation_ids=expected_observation_ids,
        universe_policy_version="universe-v1",
        split_policy_version="split-v1",
        cost_policy_version="cost-v1",
        liquidity_policy_version="liquidity-v1",
    )
    recorded_at = BASE_TIME + timedelta(minutes=recorded_at_offset_minutes)
    return R5RelativeValuePromotionPolicy.create(
        policy_version="policy-v1",
        scope=actual_scope,
        registration=registration,
        minimum_observation_count=2,
        minimum_coverage_ratio=Decimal("1"),
        minimum_excess_net_return=minimum_excess_net_return,
        maximum_drawdown_increase=Decimal("0.02"),
        maximum_total_cost=Decimal("0.02"),
        maximum_liquidity_breach_ratio=Decimal("0"),
        maximum_capacity_utilization=Decimal("0.90"),
        maximum_realized_credit_loss=Decimal("0.01"),
        decision_validity_seconds=3600,
        approved_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        active_from=recorded_at,
        active_until=BASE_TIME + timedelta(days=3),
    )


def make_observations(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bundles: tuple[R5PersistedRelativeValueBundle, R5PersistedRelativeValueBundle] | None = None,
) -> tuple[R5RelativeValueTrialObservation, R5RelativeValueTrialObservation]:
    """Create two exact OOS observations over distinct owner records."""

    actual_bundles = bundles or make_persisted_bundles(monkeypatch)
    observations: list[R5RelativeValueTrialObservation] = []
    for index, (observation_id, bundle) in enumerate(
        zip(("obs-a", "obs-b"), actual_bundles, strict=True),
        start=1,
    ):
        selection_at = bundle.result.recorded_at + timedelta(minutes=1)
        observed_at = selection_at + timedelta(hours=1)
        available_at = observed_at + timedelta(minutes=1)
        fixed_income_record = project_r5_relative_value_owner_record(bundle)
        portfolio_outcome = R5PortfolioOutcomeSeal.create(
            outcome_version="outcome-v1",
            owner_record_id=f"portfolio-outcome-record-{index}",
            owner_record_version="portfolio-outcome-record-v1",
            owner_record_hash=(HASH_C if index == 1 else "d" * 64),
            observation_id=observation_id,
            fixed_income_result_id=fixed_income_record.result_id,
            fixed_income_result_version=fixed_income_record.result_version,
            fixed_income_result_record_hash=fixed_income_record.result_record_hash,
            fixed_income_owner_seal_hash=fixed_income_record.content_hash,
            selection_as_of=selection_at,
            outcome_observed_at=observed_at,
            outcome_available_at=available_at,
            recorded_at=available_at + timedelta(minutes=1),
            valid_until=BASE_TIME + timedelta(days=2),
            target_gross_return=Decimal("0.020") + Decimal(index) / Decimal("1000"),
            target_cost=Decimal("0.002"),
            benchmark_gross_return=Decimal("0.010"),
            benchmark_cost=Decimal("0.001"),
            target_maximum_drawdown=Decimal("0.03"),
            benchmark_maximum_drawdown=Decimal("0.025"),
            capacity_utilization=Decimal("0.70"),
            liquidity_breached=False,
            realized_credit_loss=Decimal("0.001"),
        )
        observations.append(
            R5RelativeValueTrialObservation.create(
                observation_id=observation_id,
                fixed_income_record=fixed_income_record,
                portfolio_outcome=portfolio_outcome,
            )
        )
    return observations[0], observations[1]


def make_trial(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: R5RelativeValuePromotionPolicy | None = None,
    observations: (
        tuple[
            R5RelativeValueTrialObservation,
            R5RelativeValueTrialObservation,
        ]
        | None
    ) = None,
) -> R5RelativeValuePromotionTrial:
    """Create a complete exact R5 promotion trial."""

    actual_policy = policy or make_policy()
    return R5RelativeValuePromotionTrial.create(
        policy=actual_policy,
        observations=observations or make_observations(monkeypatch),
        evaluated_at=BASE_TIME + timedelta(hours=3),
    )


def make_decision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: R5RelativeValuePromotionPolicy | None = None,
    trial: R5RelativeValuePromotionTrial | None = None,
    decided_at_offset_minutes: int = 181,
) -> R5RelativeValuePromotionDecision:
    """Create one approved, content-addressed R5 promotion decision."""

    actual_policy = policy or make_policy()
    actual_trial = trial or make_trial(monkeypatch, policy=actual_policy)
    decided_at = BASE_TIME + timedelta(minutes=decided_at_offset_minutes)
    return create_r5_relative_value_promotion_decision(
        policy=actual_policy,
        trial=actual_trial,
        decided_at=decided_at,
        recorded_at=decided_at + timedelta(seconds=30),
    )
