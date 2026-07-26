"""Financial-truthfulness tests for the stock-selection backtest."""

from datetime import date
from decimal import Decimal

import pytest

from apps.backtest.domain.stock_selection_backtest import (
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
)
from apps.equity.domain.rules import StockScreeningRule


def _rule() -> dict[str, StockScreeningRule]:
    return {
        "Recovery": StockScreeningRule(
            regime="Recovery",
            name="test",
        )
    }


def _engine(
    *,
    config: StockSelectionBacktestConfig,
    stock_reader,
    price_reader,
) -> StockSelectionBacktestEngine:
    return StockSelectionBacktestEngine(
        config=config,
        get_regime_func=lambda as_of: "Recovery",
        get_stock_data_func=stock_reader,
        get_price_func=price_reader,
        get_benchmark_price_func=lambda as_of: 100.0,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"initial_capital": Decimal("NaN")},
        {"initial_capital": Decimal("0")},
        {"max_positions": 0},
        {"position_method": "unknown"},
        {"commission_rate": float("nan")},
        {"slippage_rate": -0.01},
        {"annual_risk_free_rate": float("inf")},
    ],
)
def test_stock_selection_config_rejects_invalid_financial_inputs(
    overrides: dict[str, object],
) -> None:
    """Invalid capital, capacity, weighting, rates, and risk inputs fail early."""

    values: dict[str, object] = {
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 2, 1),
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        StockSelectionBacktestConfig(**values)


def test_month_end_rebalance_dates_are_calendar_safe() -> None:
    """Monthly schedules clamp month ends instead of raising on February."""

    config = StockSelectionBacktestConfig(
        start_date=date(2024, 1, 31),
        end_date=date(2024, 4, 30),
    )
    engine = _engine(
        config=config,
        stock_reader=lambda as_of: [],
        price_reader=lambda code, as_of: Decimal("100"),
    )

    assert engine._generate_rebalance_dates() == [
        date(2024, 1, 31),
        date(2024, 2, 29),
        date(2024, 3, 29),
        date(2024, 4, 29),
    ]


def test_stock_selection_fails_closed_on_missing_held_exit_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A held stock cannot disappear when the rebalance exit quote is absent."""

    first_date = date(2026, 1, 1)
    second_date = date(2026, 2, 1)
    config = StockSelectionBacktestConfig(
        start_date=first_date,
        end_date=second_date,
        initial_capital=Decimal("1000"),
        max_positions=1,
        commission_rate=0.0,
        slippage_rate=0.0,
    )
    monkeypatch.setattr(
        "apps.backtest.domain.stock_selection_backtest.StockScreener.screen",
        lambda self, stocks, rule: ["AAA"] if stocks[0] == first_date else ["BBB"],
    )

    def price_reader(code: str, as_of: date) -> Decimal | None:
        if code == "AAA" and as_of == second_date:
            return None
        return Decimal("100")

    with pytest.raises(ValueError, match="Missing valid exit price for AAA"):
        _engine(
            config=config,
            stock_reader=lambda as_of: [as_of],
            price_reader=price_reader,
        ).run(_rule())


def test_stock_selection_requires_regime_and_executable_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing decision context or all-empty data cannot publish a zero-return run."""

    trade_date = date(2026, 1, 1)
    config = StockSelectionBacktestConfig(start_date=trade_date, end_date=trade_date)
    no_regime = StockSelectionBacktestEngine(
        config=config,
        get_regime_func=lambda as_of: None,
        get_stock_data_func=lambda as_of: [as_of],
        get_price_func=lambda code, as_of: Decimal("100"),
        get_benchmark_price_func=lambda as_of: 100.0,
    )
    with pytest.raises(ValueError, match="Regime is unavailable"):
        no_regime.run(_rule())

    monkeypatch.setattr(
        "apps.backtest.domain.stock_selection_backtest.StockScreener.screen",
        lambda self, stocks, rule: [],
    )
    with pytest.raises(ValueError, match="no executable observations"):
        _engine(
            config=config,
            stock_reader=lambda as_of: [],
            price_reader=lambda code, as_of: Decimal("100"),
        ).run(_rule())


def test_stock_selection_terminal_metrics_include_real_liquidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal commission, trade count, dates, and equity share one truth."""

    trade_date = date(2026, 1, 1)
    config = StockSelectionBacktestConfig(
        start_date=trade_date,
        end_date=trade_date,
        initial_capital=Decimal("1001"),
        max_positions=1,
        commission_rate=0.001,
        slippage_rate=0.0,
    )
    monkeypatch.setattr(
        "apps.backtest.domain.stock_selection_backtest.StockScreener.screen",
        lambda self, stocks, rule: ["AAA"],
    )
    result = _engine(
        config=config,
        stock_reader=lambda as_of: [as_of],
        price_reader=lambda code, as_of: Decimal("100"),
    ).run(_rule())

    assert result.total_trades == 2
    assert result.total_rebalances == 1
    assert result.equity_curve[-1] == (trade_date, Decimal("999.000"))
    assert result.total_return == pytest.approx(float(Decimal("-2") / Decimal("1001")))
    assert result.stock_performances[0].entry_date == trade_date
    assert result.stock_performances[0].exit_price == Decimal("100")
    assert result.stock_performances[0].holding_days == 0
