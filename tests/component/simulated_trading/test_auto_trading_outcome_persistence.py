"""Exercise result accounting against the ordinary, still non-atomic order path.

Prices, candidates, risk acceptance and strategy selection are local fixtures.
These tests do not qualify a market source or activate the candidate settlement
UoW. Database writes use the actual order use case and Django repositories.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model

from apps.risk_center.application.trade_guard import PreTradeRiskCheckResult
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.daily_net_value_service import DailyNetValueService
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.domain.auto_trading_outcomes import AutoTradingOutcome
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoFeeConfigRepository,
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def persisted_account(monkeypatch: pytest.MonkeyPatch) -> SimulatedAccountModel:
    """Create explicit legacy test fees and a simulated account in the test DB."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    owner = get_user_model().objects.create_user(username="ash-outcome-owner")
    FeeConfigModel.objects.filter(asset_type="equity", is_default=True).update(is_default=False)
    FeeConfigModel.objects.create(
        config_name="ash-outcome-local-legacy-fixture",
        asset_type="equity",
        min_commission=5.0,
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.0,
        slippage_rate=0.0,
        is_default=True,
        is_active=True,
    )
    return SimulatedAccountModel.objects.create(
        user=owner,
        account_name="ash-outcome-persistence",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
        auto_trading_enabled=True,
        is_active=True,
    )


def _engine(monkeypatch: pytest.MonkeyPatch) -> AutoTradingEngine:
    """Keep ordinary trade/position/account writes real; isolate external inputs."""

    account_repo = DjangoSimulatedAccountRepository()
    position_repo = DjangoPositionRepository()
    trade_repo = DjangoTradeRepository()
    fee_repo = DjangoFeeConfigRepository()
    candidates = Mock()
    candidates.get_investable_assets_with_signals.return_value = [
        {
            "asset_code": "000001.SZ",
            "asset_name": "Local fixture",
            "asset_type": "equity",
            "score": 90.0,
        }
    ]
    monkeypatch.setattr(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        lambda: SimpleNamespace(get_active_strategy_id=lambda account_id: None),
    )
    return AutoTradingEngine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        buy_use_case=ExecuteBuyOrderUseCase(account_repo, position_repo, trade_repo, fee_repo),
        sell_use_case=ExecuteSellOrderUseCase(account_repo, position_repo, trade_repo, fee_repo),
        performance_use_case=GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo),
        asset_pool_service=candidates,
        price_provider=Mock(get_price=Mock(return_value=10.0)),
        pre_trade_risk_guard=Mock(execute=Mock(return_value=PreTradeRiskCheckResult(passed=True))),
    )


@pytest.mark.parametrize("post_stage", ["link", "performance"])
def test_confirmed_database_trade_survives_post_trade_failure_in_result(
    monkeypatch: pytest.MonkeyPatch,
    persisted_account: SimulatedAccountModel,
    post_stage: str,
) -> None:
    """Actual trade, position and cash remain confirmed when later work fails."""

    engine = _engine(monkeypatch)
    if post_stage == "link":
        engine.execution_link_recorder = Mock()
        engine.execution_link_recorder.record_execution.side_effect = RuntimeError(
            "local link outage"
        )
        monkeypatch.setattr(
            engine, "_update_account_performance", lambda account_id, trade_date: True
        )
        expected_code = "EXECUTION_LINK_RECORD_FAILED"
    else:
        monkeypatch.setattr(
            DailyNetValueService,
            "record_and_update_performance",
            Mock(side_effect=RuntimeError("local performance outage")),
        )
        expected_code = "ACCOUNT_PERFORMANCE_UPDATE_FAILED"

    result = engine.run_daily_trading(date(2026, 10, 16), [persisted_account.pk])[
        persisted_account.pk
    ]
    trade = SimulatedTradeModel.objects.get(account=persisted_account)
    position = PositionModel.objects.get(account=persisted_account, asset_code="000001.SZ")
    persisted_account.refresh_from_db()

    assert result.outcome is AutoTradingOutcome.PARTIAL
    assert result.buy_count == result.confirmed_trade_count == result.stored == 1
    assert result.counts_unavailable is False
    assert {issue.code for issue in result.issues} == {expected_code}
    assert trade.execution_date == date(2026, 10, 16)
    assert Decimal(str(position.quantity)) == Decimal(str(trade.quantity))
    assert persisted_account.current_cash == Decimal("100000.00") - Decimal(str(trade.total_cost))
    assert persisted_account.total_trades == 1


def test_real_trade_row_before_position_failure_has_unknown_effect_count(
    monkeypatch: pytest.MonkeyPatch, persisted_account: SimulatedAccountModel
) -> None:
    """The legacy UC can write a trade before failing; stored must stay unknown."""

    engine = _engine(monkeypatch)
    save = Mock(side_effect=RuntimeError("local position write outage"))
    monkeypatch.setattr(engine.position_repo, "save", save)
    monkeypatch.setattr(engine, "_update_account_performance", lambda account_id, trade_date: True)

    result = engine.run_daily_trading(date(2026, 10, 16), [persisted_account.pk])[
        persisted_account.pk
    ]
    persisted_account.refresh_from_db()

    assert SimulatedTradeModel.objects.filter(account=persisted_account).count() == 1
    assert not PositionModel.objects.filter(account=persisted_account).exists()
    assert persisted_account.current_cash == Decimal("100000.00")
    assert persisted_account.total_trades == 0
    assert save.call_count == 1
    assert result.outcome is AutoTradingOutcome.FAILED
    assert result.buy_count == result.confirmed_trade_count == 0
    assert result.stored is None
    assert result.counts_unavailable is True
    assert {issue.code for issue in result.issues} == {"BUY_EXECUTION_OUTCOME_UNKNOWN"}
    assert all(issue.effects_indeterminate for issue in result.issues)
