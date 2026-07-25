"""Persistence lifecycle contracts for strategy repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.strategy.domain.entities import (
    ActionType,
    RiskControlParams,
    RuleCondition,
    RuleType,
    SignalRecommendation,
    Strategy,
    StrategyConfig,
    StrategyExecutionResult,
    StrategyType,
)
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    StrategyExecutionLogModel,
    StrategyModel,
)
from apps.strategy.infrastructure.repositories import (
    DjangoRuleConditionRepository,
    DjangoStrategyExecutionLogRepository,
    DjangoStrategyRepository,
    StrategyParamRepository,
)


def _owner_and_portfolio() -> tuple[AccountProfileModel, SimulatedAccountModel]:
    suffix = uuid4().hex[:8]
    user = User.objects.create_user(username=f"strategy-repo-{suffix}")
    profile = AccountProfileModel.objects.get(user=user)
    portfolio = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"Strategy portfolio {suffix}",
        account_type="simulated",
        initial_capital=100000,
        current_cash=100000,
        current_market_value=0,
        total_value=100000,
    )
    return profile, portfolio


def _rule(strategy_id: int | None = None) -> RuleCondition:
    return RuleCondition(
        rule_id=None,
        strategy_id=strategy_id,
        rule_name="PMI recovery",
        rule_type=RuleType.MACRO,
        condition_json={"operator": "gt", "field": "PMI", "value": 50},
        action=ActionType.BUY,
        weight=0.4,
        target_assets=["000001.SH"],
        priority=10,
    )


def _strategy(profile_id: int) -> Strategy:
    risk = RiskControlParams(
        max_position_pct=15,
        max_total_position_pct=80,
        stop_loss_pct=8,
    )
    return Strategy(
        strategy_id=None,
        name=f"Repository strategy {uuid4().hex[:8]}",
        strategy_type=StrategyType.RULE_BASED,
        version=1,
        is_active=True,
        created_by_id=profile_id,
        config=StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk,
            description="repository contract",
        ),
        risk_params=risk,
        rule_conditions=[_rule()],
        description="repository contract",
    )


@pytest.mark.django_db
def test_strategy_and_rule_repository_full_lifecycle() -> None:
    """Strategies and their typed rules round-trip, update, filter, and delete."""
    profile, portfolio = _owner_and_portfolio()
    repository = DjangoStrategyRepository()
    strategy = _strategy(profile.id)

    strategy_id = repository.save(strategy)
    loaded = repository.get_by_id(strategy_id)
    assert loaded is not None
    assert loaded.name == strategy.name
    assert loaded.rule_conditions is not None
    assert loaded.rule_conditions[0].action is ActionType.BUY
    assert repository.get_by_id(999999999) is None
    assert [item.strategy_id for item in repository.get_by_user(profile.id)] == [strategy_id]

    loaded.name = f"{loaded.name} updated"
    loaded.version = 2
    repository.save(loaded)
    assert repository.get_by_id(strategy_id).version == 2

    PortfolioStrategyAssignmentModel.objects.create(
        portfolio=portfolio,
        strategy_id=strategy_id,
        assigned_by=profile,
        is_active=True,
    )
    assigned = repository.get_active_strategies_for_portfolio(portfolio.id)
    assert [item.strategy_id for item in assigned] == [strategy_id]

    rule_repository = DjangoRuleConditionRepository()
    replacement = _rule(strategy_id)
    replacement.rule_name = "Updated PMI recovery"
    rule_id = rule_repository.save(replacement)
    saved_rule = rule_repository.get_by_strategy(strategy_id)[0]
    assert saved_rule.rule_id == rule_id
    saved_rule.action = ActionType.SELL
    saved_rule.priority = 20
    rule_repository.save(saved_rule)
    assert rule_repository.get_by_strategy(strategy_id)[0].action is ActionType.SELL
    assert rule_repository.delete_by_strategy(strategy_id) is True
    assert rule_repository.delete_by_strategy(strategy_id) is False

    assert repository.delete(strategy_id) is True
    assert repository.delete(strategy_id) is False


@pytest.mark.django_db
def test_execution_log_and_parameter_repository_contracts() -> None:
    """Execution history and inactive parameter versions retain JSON-safe values."""
    profile, portfolio = _owner_and_portfolio()
    strategy_repository = DjangoStrategyRepository()
    strategy_id = strategy_repository.save(_strategy(profile.id))
    execution_repository = DjangoStrategyExecutionLogRepository()
    result = StrategyExecutionResult(
        strategy_id=strategy_id,
        portfolio_id=portfolio.id,
        execution_time=datetime.now(UTC),
        execution_duration_ms=12,
        signals=[
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="Index",
                action=ActionType.BUY,
                weight=0.3,
                reason="recovery",
                confidence=0.9,
                metadata={"source": "contract"},
            )
        ],
        is_success=True,
        context={"regime": "Recovery"},
    )
    log_id = execution_repository.save(result)
    assert log_id > 0
    assert execution_repository.get_by_strategy(strategy_id)[0].signals[0].weight == 0.3
    assert execution_repository.get_by_portfolio(portfolio.id)[0].context == {"regime": "Recovery"}
    assert execution_repository.save(replace(result, strategy_id=999999999)) == 0

    params = StrategyParamRepository()
    assert params.get_active_params(strategy_id) == {}
    saved = params.save_params(
        strategy_id,
        {"lookback": 20},
        version=1,
        change_description="candidate",
        changed_by_id=profile.id,
        set_as_active=False,
    )
    assert saved is not None
    assert params.get_active_params(strategy_id) == {}
    assert params.save_params(999999999, {}, version=1, set_as_active=False) is None
    assert params.rollback_to_version(strategy_id, 999) is False


@pytest.mark.django_db
def test_strategy_numeric_invariants_survive_direct_orm_updates() -> None:
    """Database constraints protect risk controls from ORM validation bypasses."""

    profile, portfolio = _owner_and_portfolio()
    strategy = StrategyModel.objects.create(
        name=f"Invariant strategy {uuid4().hex[:8]}",
        strategy_type="rule_based",
        created_by=profile,
    )
    position_rule = PositionManagementRuleModel.objects.create(
        strategy=strategy,
        name="Invariant position rule",
        buy_price_expr="current_price",
        sell_price_expr="current_price",
        stop_loss_expr="current_price",
        take_profit_expr="current_price",
        position_size_expr="1",
    )
    rule = RuleConditionModel.objects.create(
        strategy=strategy,
        rule_name="Invariant rule",
        rule_type="macro",
        condition_json={"field": "PMI", "operator": "gt", "value": 50},
        action="buy",
        weight=0.5,
    )
    ai_config = AIStrategyConfigModel.objects.create(strategy=strategy)
    assignment = PortfolioStrategyAssignmentModel.objects.create(
        portfolio=portfolio,
        strategy=strategy,
        assigned_by=profile,
    )
    execution_log = StrategyExecutionLogModel.objects.create(
        strategy=strategy,
        portfolio=portfolio,
        execution_duration_ms=1,
        execution_result={"status": "completed"},
        signals_generated=[],
    )

    invalid_updates = [
        (StrategyModel, strategy.pk, {"max_position_pct": -1}),
        (
            PositionManagementRuleModel,
            position_rule.pk,
            {"price_precision": 9},
        ),
        (RuleConditionModel, rule.pk, {"weight": 1.1}),
        (AIStrategyConfigModel, ai_config.pk, {"max_tokens": 0}),
        (
            PortfolioStrategyAssignmentModel,
            assignment.pk,
            {"override_stop_loss_pct": 101},
        ),
        (
            StrategyExecutionLogModel,
            execution_log.pk,
            {"execution_duration_ms": -1},
        ),
    ]

    for model, object_id, update_values in invalid_updates:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=object_id).update(**update_values)
