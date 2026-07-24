"""Focused tests for simulated-account performance calculations."""

from datetime import UTC, date, datetime

import pytest

from apps.simulated_trading.application.performance_calculator import (
    PerformanceCalculator,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    OrderStatus,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from core.exceptions import DataFetchError


class _AccountRepository:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account
        self.saved: SimulatedAccount | None = None

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if self.account.account_id == account_id else None

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int:
        self.saved = account
        return account.account_id


class _TradeRepository:
    def __init__(self, trades: list[SimulatedTrade]) -> None:
        self.trades = trades
        self.requested_end_dates: list[date] = []

    def get_by_date_range(
        self,
        account_id: int,
        start: date,
        end: date,
    ) -> list[SimulatedTrade]:
        self.requested_end_dates.append(end)
        return [
            trade
            for trade in self.trades
            if trade.account_id == account_id and start <= trade.execution_date <= end
        ]


class _PriceProvider:
    def __init__(self, price: float | None) -> None:
        self.price = price

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        return self.price

    def require_price(self, asset_code: str, trade_date: date) -> float:
        if self.price is None:
            raise DataFetchError(message="missing price", code="PRICE_UNAVAILABLE")
        return self.price


def _build_account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="performance",
        account_type=AccountType.SIMULATED,
        initial_capital=100.0,
        current_cash=121.0,
        current_market_value=0.0,
        total_value=121.0,
        total_return=0.0,
        start_date=date(2025, 7, 24),
    )


def _build_trade(
    *,
    trade_id: int,
    execution_date: date,
    action: TradeAction,
    realized_pnl: float | None,
) -> SimulatedTrade:
    return SimulatedTrade(
        trade_id=trade_id,
        account_id=1,
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_type="equity",
        action=action,
        quantity=1.0,
        price=10.0,
        amount=10.0,
        order_date=execution_date,
        execution_date=execution_date,
        execution_time=datetime.combine(
            execution_date,
            datetime.min.time(),
            tzinfo=UTC,
        ),
        total_cost=10.0 if action == TradeAction.BUY else 0.0,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl,
        status=OrderStatus.EXECUTED,
    )


def test_annual_return_uses_current_account_value_not_stored_metric() -> None:
    account = _build_account()
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=_TradeRepository([]),
        price_provider=_PriceProvider(10.0),
    )

    metrics = calculator._calculate_metrics(account, date(2026, 7, 24))

    assert metrics["total_return"] == pytest.approx(21.0)
    assert metrics["annual_return"] == pytest.approx(21.0)


def test_win_rate_counts_only_closed_trades_before_as_of_date() -> None:
    trades = [
        _build_trade(
            trade_id=1,
            execution_date=date(2026, 7, 20),
            action=TradeAction.BUY,
            realized_pnl=None,
        ),
        _build_trade(
            trade_id=2,
            execution_date=date(2026, 7, 21),
            action=TradeAction.SELL,
            realized_pnl=5.0,
        ),
        _build_trade(
            trade_id=3,
            execution_date=date(2026, 7, 22),
            action=TradeAction.SELL,
            realized_pnl=-2.0,
        ),
        _build_trade(
            trade_id=4,
            execution_date=date(2026, 7, 25),
            action=TradeAction.SELL,
            realized_pnl=3.0,
        ),
    ]
    trade_repo = _TradeRepository(trades)
    account = _build_account()
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=trade_repo,
        price_provider=_PriceProvider(10.0),
    )

    win_rate, winning_trades = calculator._calculate_win_rate(
        account,
        date(2026, 7, 24),
    )

    assert win_rate == pytest.approx(50.0)
    assert winning_trades == 1
    assert trade_repo.requested_end_dates == [date(2026, 7, 24)]


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_market_price_must_be_finite_and_positive(price: float) -> None:
    account = _build_account()
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=_TradeRepository([]),
        price_provider=_PriceProvider(price),
    )

    with pytest.raises(DataFetchError, match="有效历史价格"):
        calculator._require_market_price("000001.SZ", date(2026, 7, 24))
