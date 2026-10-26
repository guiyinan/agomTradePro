"""Focused tests for simulated-account performance calculations."""

from datetime import UTC, date, datetime, time, timedelta
from datetime import timezone as datetime_timezone
from decimal import Decimal, Inexact, Rounded, localcontext
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError

from apps.simulated_trading.application import performance_calculator as calculator_module
from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionCashPosting,
)
from apps.simulated_trading.application.performance_calculator import (
    PerformanceCalculator,
)
from apps.simulated_trading.application.ports import AccountPerformanceUpdate
from apps.simulated_trading.domain.entities import (
    AccountType,
    OrderStatus,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.domain.fee_correction import FeeCorrectionCashEvent
from core.exceptions import DataFetchError, InvalidInputError


class _AccountRepository:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account
        self.saved: AccountPerformanceUpdate | None = None
        self.read_calls = 0
        self.update_calls = 0

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        self.read_calls += 1
        return self.account if self.account.account_id == account_id else None

    def update_performance_metrics(
        self,
        *,
        account_id: int,
        expected_account: SimulatedAccount,
        metrics: AccountPerformanceUpdate,
    ) -> None:
        assert account_id == expected_account.account_id
        assert expected_account is self.account
        self.update_calls += 1
        self.saved = metrics


class _TradeRepository:
    def __init__(
        self,
        trades: list[SimulatedTrade],
        *,
        history_error: DatabaseError | None = None,
        cash_events: tuple[FeeCorrectionCashPosting, ...] = (),
    ) -> None:
        self.trades = trades
        self.history_error = history_error
        self.cash_events = cash_events
        self.history_requests: list[tuple[int, datetime, date | None, date | None]] = []

    def get_by_date_range(
        self,
        account_id: int,
        start: date,
        end: date,
        *,
        as_of: datetime | None = None,
    ) -> list[SimulatedTrade]:
        return [
            trade
            for trade in self.trades
            if trade.account_id == account_id
            and start <= trade.execution_date <= end
            and (as_of is None or trade.execution_time <= as_of)
        ]

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        self.history_requests.append((account_id, as_of, start_date, end_date))
        if self.history_error is not None:
            raise self.history_error
        trades = tuple(
            trade
            for trade in self.trades
            if trade.account_id == account_id
            and (start_date is None or start_date <= trade.execution_date)
            and (end_date is None or trade.execution_date <= end_date)
            and trade.execution_time <= as_of
        )
        return FeeCorrectionAccountHistoryProjection(
            account_id=account_id,
            as_of=as_of,
            trades=trades,
            cash_events=self.cash_events,
        )


class _PriceProvider:
    def __init__(self, price: float | None) -> None:
        self.price = price
        self.calls: list[tuple[str, date, str]] = []

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        self.calls.append((asset_code, trade_date, "get"))
        return self.price

    def require_price(self, asset_code: str, trade_date: date) -> float:
        self.calls.append((asset_code, trade_date, "require"))
        if self.price is None:
            raise DataFetchError(message="missing price", code="PRICE_UNAVAILABLE")
        return self.price


class _FailingPriceProvider:
    def require_price(self, asset_code: str, trade_date: date) -> float:
        raise DatabaseError("historical price read failed")


def _build_account(*, initial_capital: float = 100.0) -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="performance",
        account_type=AccountType.SIMULATED,
        initial_capital=initial_capital,
        current_cash=121.0,
        current_market_value=0.0,
        total_value=121.0,
        total_return=0.0,
        start_date=date(2025, 7, 24),
    )


def _pin_business_date(monkeypatch: pytest.MonkeyPatch, business_date: date) -> None:
    """Keep current-cache tests aligned with Django's configured business date."""
    monkeypatch.setattr(
        calculator_module.timezone,
        "localdate",
        lambda value=None, timezone=None: business_date,
    )


def _build_trade(
    *,
    trade_id: int,
    execution_date: date,
    action: TradeAction,
    realized_pnl: float | None,
    amount: float = 10.0,
    commission: float = 0.0,
    slippage: float = 0.0,
    total_cost: float | None = None,
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
        amount=amount,
        order_date=execution_date,
        execution_date=execution_date,
        execution_time=datetime.combine(
            execution_date,
            datetime.min.time(),
            tzinfo=UTC,
        ),
        commission=commission,
        slippage=slippage,
        total_cost=(
            (10.0 if action == TradeAction.BUY else 0.0) if total_cost is None else total_cost
        ),
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl,
        status=OrderStatus.EXECUTED,
    )


def _build_cash_posting(
    *,
    event_id: int,
    posting_date: date,
    cash_delta: Decimal,
) -> FeeCorrectionCashPosting:
    return FeeCorrectionCashPosting(
        event=FeeCorrectionCashEvent(
            event_id=event_id,
            posting_date=posting_date,
            posted_at=datetime.combine(posting_date, datetime.min.time(), tzinfo=UTC),
            cash_delta=cash_delta,
        ),
        account_revision=event_id,
        account_prefix_sha256=f"{event_id:064x}",
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


def test_performance_update_uses_metric_only_repository_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = date(2026, 7, 24)
    _pin_business_date(monkeypatch, trade_date)
    account = _build_account()
    account_repo = _AccountRepository(account)
    calculator = PerformanceCalculator(
        account_repo=account_repo,
        trade_repo=_TradeRepository([]),
        price_provider=_PriceProvider(10.0),
    )

    metrics = calculator.calculate_and_update_performance(1, trade_date)

    assert account_repo.saved is not None
    assert account_repo.saved.total_return == pytest.approx(21.0)
    assert account_repo.saved.annual_return == pytest.approx(21.0)
    assert account_repo.saved.max_drawdown == 0.0
    assert account_repo.saved.sharpe_ratio == 0.0
    assert account_repo.saved.win_rate == 0.0
    assert account_repo.saved.winning_trades == 0
    assert metrics["total_return"] == pytest.approx(21.0)


def test_current_cache_uses_default_business_timezone_for_guard_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active UTC timezone cannot shift configured current-day cache writes."""
    instant = datetime(2026, 10, 25, 20, 15, tzinfo=UTC)
    monkeypatch.setattr(calculator_module.timezone, "now", lambda: instant)
    account = _build_account()
    account_repo = _AccountRepository(account)
    trade_repo = _TradeRepository([])
    calculator = PerformanceCalculator(
        account_repo=account_repo,
        trade_repo=trade_repo,
        price_provider=_PriceProvider(10.0),
    )

    with calculator_module.timezone.override(ZoneInfo("UTC")):
        default_timezone = calculator_module.timezone.get_default_timezone()
        business_today = instant.astimezone(default_timezone).date()
        assert business_today == date(2026, 10, 26)

        metrics = calculator.calculate_and_update_performance(1, business_today)

        assert metrics["total_return"] == pytest.approx(21.0)
        assert account_repo.read_calls == 1
        assert account_repo.update_calls == 1
        assert trade_repo.history_requests
        assert all(request[1] == instant for request in trade_repo.history_requests)

        with pytest.raises(InvalidInputError) as captured:
            calculator.calculate_and_update_performance(1, instant.date())

    assert captured.value.code == "PERFORMANCE_CURRENT_DATE_REQUIRED"
    assert account_repo.read_calls == 1
    assert account_repo.update_calls == 1


def test_history_as_of_uses_default_timezone_when_active_timezone_is_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured current-day history uses now despite an ahead active timezone."""
    instant = datetime(2026, 10, 25, 10, 15, tzinfo=UTC)
    monkeypatch.setattr(calculator_module.timezone, "now", lambda: instant)
    default_timezone = calculator_module.timezone.get_default_timezone()
    business_today = instant.astimezone(default_timezone).date()

    with calculator_module.timezone.override(datetime_timezone(timedelta(hours=14))):
        assert instant.astimezone(calculator_module.timezone.get_current_timezone()).date() > (
            business_today
        )
        assert calculator_module._history_as_of(business_today) == instant

        historical_date = business_today - timedelta(days=1)
        historical_as_of = calculator_module._history_as_of(historical_date)

    assert historical_as_of.astimezone(default_timezone).date() == historical_date
    assert historical_as_of.astimezone(default_timezone).time() == time.max


@pytest.mark.parametrize(
    "requested_date",
    [
        date(2026, 10, 24),
        date(2026, 10, 26),
        datetime(2026, 10, 25, 12, tzinfo=UTC),
    ],
    ids=["historical-after-current-fee-change", "future", "datetime-is-not-date"],
)
def test_current_cache_update_rejects_non_current_date_before_any_io(
    monkeypatch: pytest.MonkeyPatch,
    requested_date: date | datetime,
) -> None:
    """Do not persist present-day totals under a different historical date."""
    business_today = date(2026, 10, 25)
    _pin_business_date(monkeypatch, business_today)
    account = _build_account()
    account_repo = _AccountRepository(account)
    posting = _build_cash_posting(
        event_id=1,
        posting_date=business_today,
        cash_delta=Decimal("1.00"),
    )
    trade_repo = _TradeRepository([], cash_events=(posting,))
    price_provider = _PriceProvider(10.0)
    calculator = PerformanceCalculator(
        account_repo=account_repo,
        trade_repo=trade_repo,
        price_provider=price_provider,
    )

    with pytest.raises(InvalidInputError) as captured:
        calculator.calculate_and_update_performance(1, requested_date)

    assert captured.value.code == "PERFORMANCE_CURRENT_DATE_REQUIRED"
    assert account_repo.read_calls == 0
    assert account_repo.update_calls == 0
    assert account_repo.saved is None
    assert trade_repo.history_requests == []
    assert price_provider.calls == []


def test_current_cache_date_is_allowed_and_historical_curve_remains_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep current metrics writable without restricting historical curve reads."""
    business_today = date(2026, 10, 25)
    historical_end = date(2026, 10, 20)
    _pin_business_date(monkeypatch, business_today)
    account = _build_account()
    account_repo = _AccountRepository(account)
    trade_repo = _TradeRepository([])
    calculator = PerformanceCalculator(
        account_repo=account_repo,
        trade_repo=trade_repo,
        price_provider=_PriceProvider(10.0),
    )

    metrics = calculator.calculate_and_update_performance(1, business_today)
    curve = calculator.get_equity_curve(
        account_id=1,
        start_date=account.start_date,
        end_date=historical_end,
    )

    assert metrics["total_return"] == pytest.approx(21.0)
    assert account_repo.saved is not None
    assert curve[0]["date"] == account.start_date.isoformat()
    assert trade_repo.history_requests[-1][1].date() == historical_end
    assert trade_repo.history_requests[-1][3] == historical_end


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
    assert trade_repo.history_requests[0][0] == account.account_id
    assert trade_repo.history_requests[0][1].date() == date(2026, 7, 24)
    assert trade_repo.history_requests[0][2:] == (
        account.start_date,
        date(2026, 7, 24),
    )


@pytest.mark.parametrize("hostile_decimal_context", [False, True])
def test_equity_curve_sums_cash_events_exactly_by_posting_date(
    hostile_decimal_context: bool,
) -> None:
    postings = (
        _build_cash_posting(
            event_id=1,
            posting_date=date(2026, 7, 20),
            cash_delta=Decimal("0.10"),
        ),
        _build_cash_posting(
            event_id=2,
            posting_date=date(2026, 7, 20),
            cash_delta=Decimal("0.20"),
        ),
        _build_cash_posting(
            event_id=3,
            posting_date=date(2026, 7, 21),
            cash_delta=Decimal("-0.10"),
        ),
    )
    account = _build_account(initial_capital=0.01)
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=_TradeRepository([], cash_events=postings),
        price_provider=_PriceProvider(10.0),
    )

    if hostile_decimal_context:
        with localcontext() as context:
            context.prec = 1
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            curve = calculator._build_equity_curve(account, date(2026, 7, 24))
    else:
        curve = calculator._build_equity_curve(account, date(2026, 7, 24))

    assert [point["date"] for point in curve] == ["2026-07-20", "2026-07-21"]
    assert [point["cash"] for point in curve] == [0.31, 0.21]


def test_equity_curve_keeps_original_trade_fee_fields_unchanged() -> None:
    buy = _build_trade(
        trade_id=1,
        execution_date=date(2026, 7, 20),
        action=TradeAction.BUY,
        realized_pnl=None,
        commission=0.10,
        slippage=0.25,
        total_cost=10.35,
    )
    sell = _build_trade(
        trade_id=2,
        execution_date=date(2026, 7, 20),
        action=TradeAction.SELL,
        realized_pnl=1.0,
        amount=11.31,
        commission=0.10,
        slippage=0.01,
        total_cost=0.11,
    )
    original_fee_fields = tuple(
        (trade.commission, trade.slippage, trade.total_cost) for trade in (buy, sell)
    )
    posting = _build_cash_posting(
        event_id=1,
        posting_date=date(2026, 7, 20),
        cash_delta=Decimal("0.30"),
    )
    account = _build_account()
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=_TradeRepository([buy, sell], cash_events=(posting,)),
        price_provider=_PriceProvider(10.0),
    )

    curve = calculator._build_equity_curve(account, date(2026, 7, 24))

    assert curve[0]["cash"] == pytest.approx(101.15)
    assert (
        tuple((trade.commission, trade.slippage, trade.total_cost) for trade in (buy, sell))
        == original_fee_fields
    )


def test_history_read_failure_does_not_persist_zero_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = date(2026, 7, 24)
    _pin_business_date(monkeypatch, trade_date)
    account = _build_account()
    account_repo = _AccountRepository(account)
    trade_repo = _TradeRepository([], history_error=DatabaseError("history read failed"))
    calculator = PerformanceCalculator(
        account_repo=account_repo,
        trade_repo=trade_repo,
        price_provider=_PriceProvider(10.0),
    )

    with pytest.raises(DatabaseError, match="history read failed"):
        calculator.calculate_and_update_performance(1, trade_date)

    assert account_repo.saved is None


@pytest.mark.parametrize(
    "metric_name",
    ["_calculate_win_rate", "_calculate_sharpe_ratio", "_calculate_max_drawdown"],
)
def test_metric_history_read_failure_is_not_reported_as_zero(metric_name: str) -> None:
    account = _build_account()
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=_TradeRepository([], history_error=DatabaseError("history read failed")),
        price_provider=_PriceProvider(10.0),
    )

    metric = getattr(calculator, metric_name)
    with pytest.raises(DatabaseError, match="history read failed"):
        metric(account, date(2026, 7, 24))


def test_max_drawdown_price_read_failure_is_not_reported_as_zero() -> None:
    account = _build_account()
    trade_repo = _TradeRepository(
        [
            _build_trade(
                trade_id=1,
                execution_date=date(2026, 7, 20),
                action=TradeAction.BUY,
                realized_pnl=None,
            )
        ]
    )
    calculator = PerformanceCalculator(
        account_repo=_AccountRepository(account),
        trade_repo=trade_repo,
        price_provider=_FailingPriceProvider(),
    )

    with pytest.raises(DatabaseError, match="historical price read failed"):
        calculator._calculate_max_drawdown(account, date(2026, 7, 24))


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
