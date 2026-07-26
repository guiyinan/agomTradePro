"""Financial-truthfulness tests for the Alpha backtest engine."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from apps.backtest.domain.alpha_backtest import AlphaBacktestConfig, AlphaBacktestEngine


@dataclass
class _Score:
    code: str
    score: float
    asof_date: date | None
    intended_trade_date: date | None


@dataclass
class _Result:
    success: bool
    scores: list[_Score]
    source: str = "test"
    error_message: str | None = None


class _Service:
    def __init__(self, scores_by_date: dict[date, list[_Score]]) -> None:
        self.scores_by_date = scores_by_date

    def get_stock_scores(
        self,
        *,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
    ) -> _Result:
        del universe_id, top_n
        return _Result(True, self.scores_by_date.get(intended_trade_date, []))


def _score(code: str, trade_date: date, *, value: float = 0.8) -> _Score:
    return _Score(code, value, trade_date, trade_date)


def _engine(
    *,
    config: AlphaBacktestConfig,
    service: _Service,
    price_reader,
) -> AlphaBacktestEngine:
    return AlphaBacktestEngine(
        config=config,
        get_regime_func=lambda as_of: "Recovery",
        get_price_func=price_reader,
        get_benchmark_price_func=lambda as_of: 100.0,
        alpha_service=service,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"initial_capital": Decimal("NaN")},
        {"initial_capital": Decimal("0")},
        {"min_score": float("nan")},
        {"min_score": float("inf")},
        {"max_positions": 0},
        {"commission_rate": float("nan")},
        {"slippage_rate": -0.01},
    ],
)
def test_alpha_backtest_config_rejects_invalid_financial_inputs(
    overrides: dict[str, object],
) -> None:
    """Invalid capital, thresholds, capacity, and rates fail before execution."""

    values: dict[str, object] = {
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 2, 1),
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        AlphaBacktestConfig(**values)


def test_alpha_backtest_fails_closed_when_held_asset_exit_price_is_missing() -> None:
    """A held position cannot disappear from capital when its exit quote is absent."""

    first_date = date(2026, 1, 1)
    second_date = date(2026, 2, 1)
    config = AlphaBacktestConfig(
        start_date=first_date,
        end_date=second_date,
        initial_capital=Decimal("1000"),
        max_positions=1,
        commission_rate=0.0,
        slippage_rate=0.0,
    )
    service = _Service(
        {
            first_date: [_score("AAA", first_date)],
            second_date: [_score("BBB", second_date)],
        }
    )

    def price_reader(code: str, as_of: date) -> Decimal | None:
        if code == "AAA" and as_of == second_date:
            return None
        return Decimal("100")

    with pytest.raises(ValueError, match="Missing valid exit price for AAA"):
        _engine(config=config, service=service, price_reader=price_reader).run()


@pytest.mark.parametrize(
    "score",
    [
        _Score("AAA", float("nan"), date(2026, 1, 1), date(2026, 1, 1)),
        _Score("AAA", 0.8, None, date(2026, 1, 1)),
        _Score("AAA", 0.8, date(2026, 1, 2), date(2026, 1, 1)),
        _Score("AAA", 0.8, date(2026, 1, 1), date(2026, 1, 2)),
    ],
)
def test_alpha_backtest_rejects_nonfinite_or_non_pit_scores(score: _Score) -> None:
    """Malformed and look-ahead scores cannot enter historical decisions."""

    trade_date = date(2026, 1, 1)
    config = AlphaBacktestConfig(start_date=trade_date, end_date=trade_date)

    with pytest.raises(ValueError):
        _engine(
            config=config,
            service=_Service({trade_date: [score]}),
            price_reader=lambda code, as_of: Decimal("100"),
        ).run()


def test_alpha_backtest_applies_exit_commission_and_terminal_equity() -> None:
    """Final return, trade count, and equity curve include terminal liquidation."""

    trade_date = date(2026, 1, 1)
    config = AlphaBacktestConfig(
        start_date=trade_date,
        end_date=trade_date,
        initial_capital=Decimal("1001"),
        max_positions=1,
        commission_rate=0.001,
        slippage_rate=0.0,
    )
    result = _engine(
        config=config,
        service=_Service({trade_date: [_score("AAA", trade_date)]}),
        price_reader=lambda code, as_of: Decimal("100"),
    ).run()

    assert result.total_trades == 2
    assert result.total_rebalances == 1
    assert result.equity_curve[-1] == (trade_date, Decimal("999.000"))
    assert result.total_return == pytest.approx(float(Decimal("-2") / Decimal("1001")))
    assert result.avg_holding_period == 0.0
