"""Pure Domain contract for corrected account performance metrics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from math import sqrt
from typing import Literal, cast

import pytest

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionCashPosting,
)
from apps.simulated_trading.application.ports import (
    DailyNetValueRecord,
    DailyNetValueRepositoryProtocol,
)
from apps.simulated_trading.application.use_cases import (
    GetAccountPerformanceUseCase,
    PositionRepositoryProtocol,
    SimulatedAccountRepositoryProtocol,
    TradeRepositoryProtocol,
    _corrected_daily_performance,
)
from apps.simulated_trading.domain.corrected_account_performance_metrics import (
    CorrectedAccountPerformanceInput,
    CorrectedAccountPerformanceMetrics,
    calculate_corrected_account_performance_metrics,
)
from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount
from apps.simulated_trading.domain.fee_correction import FeeCorrectionCashEvent


def _input(
    *,
    initial_capital: float | None = 1_000.0,
    final_net_value: float | None = 900.0,
    elapsed_days: int = 365,
    drawdowns: tuple[float | None, ...] = (0.0, 20.0, 10.0),
    daily_returns_percent: tuple[float | None, ...] = (-20.0, 12.5),
) -> CorrectedAccountPerformanceInput:
    """Build one typed Domain input with explicit known and missing values."""

    return CorrectedAccountPerformanceInput(
        initial_capital=initial_capital,
        final_net_value=final_net_value,
        elapsed_days=elapsed_days,
        drawdowns=drawdowns,
        daily_returns_percent=daily_returns_percent,
    )


def _calculate(
    input_value: CorrectedAccountPerformanceInput,
) -> CorrectedAccountPerformanceMetrics | None:
    """Call the public pure Domain operation."""

    return calculate_corrected_account_performance_metrics(input_value)


def test_sample_volatility_formula_and_negative_cumulative_return_are_preserved() -> None:
    """Use sample standard deviation, 252 trading days, and the 3% risk-free rate."""

    result = _calculate(_input())
    assert result is not None
    daily_returns = (-0.2, 0.125)
    mean_return = sum(daily_returns) / len(daily_returns)
    sample_volatility = sqrt(sum((value - mean_return) ** 2 for value in daily_returns))
    expected_sharpe = (mean_return * 252.0 - 0.03) / (sample_volatility * sqrt(252.0))

    assert result.total_return == -10.0
    assert result.annual_return == pytest.approx(-10.0)
    assert result.max_drawdown == 20.0
    assert result.sharpe_ratio == expected_sharpe


def test_positive_return_and_nonpositive_growth_boundary_keep_existing_rules() -> None:
    """Annualize positive growth and clamp zero/negative growth to -100 percent."""

    positive = _calculate(
        _input(
            initial_capital=100.0,
            final_net_value=121.0,
            drawdowns=(0.0, 4.0, 2.0),
            daily_returns_percent=(1.0, 2.0),
        )
    )
    zero_growth = _calculate(
        _input(
            initial_capital=100.0,
            final_net_value=0.0,
            drawdowns=(0.0, 100.0),
            daily_returns_percent=(10.0, -10.0),
        )
    )

    assert positive is not None
    assert zero_growth is not None
    assert positive.total_return == 21.0
    assert positive.annual_return == pytest.approx(21.0)
    assert positive.max_drawdown == 4.0
    assert zero_growth.total_return == -100.0
    assert zero_growth.annual_return == -100.0
    assert zero_growth.max_drawdown == 100.0


def test_missing_or_invalid_inputs_fail_closed() -> None:
    """Unknown coverage, bad baselines, and unusable return series yield no projection."""

    invalid_inputs = (
        _input(initial_capital=None),
        _input(initial_capital=0.0),
        _input(final_net_value=None),
        _input(elapsed_days=0),
        _input(drawdowns=()),
        _input(drawdowns=(0.0, None)),
        _input(daily_returns_percent=(1.0,)),
        _input(daily_returns_percent=(1.0, None)),
        _input(daily_returns_percent=(2.0, 2.0)),
    )

    assert all(_calculate(input_value) is None for input_value in invalid_inputs)


def test_non_finite_hostile_decimal_and_boolean_inputs_fail_closed() -> None:
    """The Domain boundary rejects non-finite floats and runtime type impostors."""

    hostile_inputs = (
        _input(final_net_value=float("nan")),
        _input(final_net_value=float("inf")),
        _input(
            initial_capital=cast(float, Decimal("sNaN")),
        ),
        _input(
            initial_capital=cast(float, True),
        ),
    )

    assert all(_calculate(input_value) is None for input_value in hostile_inputs)


def test_extreme_arithmetic_that_cannot_be_represented_fails_closed() -> None:
    """Overflow and non-finite derived values are reported as unknown."""

    excessive_annualization = _input(
        initial_capital=1.0,
        final_net_value=1e306,
        elapsed_days=1,
        drawdowns=(0.0, 1.0),
        daily_returns_percent=(1.0, 2.0),
    )
    excessive_sharpe_numerator = _input(
        drawdowns=(0.0, 1.0),
        daily_returns_percent=(1.7e308, 1.6e308),
    )

    assert _calculate(excessive_annualization) is None
    assert _calculate(excessive_sharpe_numerator) is None


class _HostileDailyRepository:
    """Return immutable synthetic rows containing a hostile database Decimal."""

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]:
        del account_id, start_date, end_date
        return [
            {
                "record_date": date(2026, 10, 1),
                "net_value": Decimal("1000.00"),
                "cash": Decimal("1000.00"),
                "market_value": Decimal("0.00"),
                "daily_return": 0.0,
                "cumulative_return": 0.0,
                "drawdown": 0.0,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 0,
                "correction_event_watermark_sha256": "0" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": False,
            },
            {
                "record_date": date(2026, 10, 2),
                "net_value": Decimal("800.00"),
                "cash": Decimal("800.00"),
                "market_value": Decimal("0.00"),
                "daily_return": -20.0,
                "cumulative_return": -20.0,
                "drawdown": 20.0,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 1,
                "correction_event_watermark_sha256": "1" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": True,
            },
            {
                "record_date": date(2026, 10, 3),
                "net_value": Decimal("sNaN"),
                "cash": Decimal("900.00"),
                "market_value": Decimal("0.00"),
                "daily_return": 12.5,
                "cumulative_return": -10.0,
                "drawdown": 10.0,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 1,
                "correction_event_watermark_sha256": "1" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": True,
            },
        ]


def test_application_normalizes_hostile_decimal_before_domain_arithmetic() -> None:
    """A signaling NaN from the repository becomes an unknown application result."""

    account = SimulatedAccount(
        account_id=5,
        account_name="synthetic-hostile-decimal",
        account_type=AccountType.SIMULATED,
        initial_capital=1_000.0,
        current_cash=900.0,
        current_market_value=0.0,
        total_value=900.0,
        start_date=date(2026, 10, 1),
    )
    event = FeeCorrectionCashPosting(
        event=FeeCorrectionCashEvent(
            event_id=1,
            posting_date=date(2026, 10, 2),
            posted_at=datetime(2026, 10, 2, 1, tzinfo=UTC),
            cash_delta=Decimal("1.00"),
        ),
        account_revision=1,
        account_prefix_sha256="a" * 64,
    )

    metrics, reason = _corrected_daily_performance(
        account=account,
        daily_net_value_repo=cast(
            DailyNetValueRepositoryProtocol,
            _HostileDailyRepository(),
        ),
        as_of=datetime(2026, 10, 4, tzinfo=UTC),
        cash_events=(event,),
    )

    assert metrics is None
    assert reason == "FEE_CORRECTION_PERFORMANCE_HISTORY_UNKNOWN"


class _BooleanAccountRepository:
    """Return one synthetic account with a malformed boolean financial field."""

    def __init__(self, account: SimulatedAccount) -> None:
        self._account = account

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self._account if account_id == self._account.account_id else None


class _NoPositionsRepository:
    """Return no positions for the synthetic account facade case."""

    def get_by_account(self, account_id: int) -> list[Position]:
        del account_id
        return []


class _CorrectionHistoryRepository:
    """Return one real typed cash posting to activate corrected-history metrics."""

    def __init__(self, posting: FeeCorrectionCashPosting) -> None:
        self._posting = posting

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        del start_date, end_date
        return FeeCorrectionAccountHistoryProjection(
            account_id=account_id,
            as_of=as_of,
            trades=(),
            cash_events=(self._posting,),
        )


class _BooleanDailyRepository:
    """Return covered synthetic rows ending in the requested malformed value."""

    def __init__(self, last_net_value: Decimal) -> None:
        self._last_net_value = last_net_value

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]:
        del account_id, start_date, end_date
        return [
            {
                "record_date": date(2026, 10, 1),
                "net_value": Decimal("1000.00"),
                "cash": Decimal("1000.00"),
                "market_value": Decimal("0.00"),
                "daily_return": 0.0,
                "cumulative_return": 0.0,
                "drawdown": 0.0,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 0,
                "correction_event_watermark_sha256": "0" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": False,
            },
            {
                "record_date": date(2026, 10, 2),
                "net_value": Decimal("800.00"),
                "cash": Decimal("800.00"),
                "market_value": Decimal("0.00"),
                "daily_return": -20.0,
                "cumulative_return": -20.0,
                "drawdown": 20.0,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 1,
                "correction_event_watermark_sha256": "1" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": True,
            },
            {
                "record_date": date(2026, 10, 3),
                "net_value": self._last_net_value,
                "cash": Decimal("1.00"),
                "market_value": Decimal("0.00"),
                "daily_return": -99.875,
                "cumulative_return": -99.9,
                "drawdown": 99.9,
                "total_trades": 0,
                "positions_count": 0,
                "correction_event_watermark": 1,
                "correction_event_watermark_sha256": "1" * 64,
                "correction_coverage_known": True,
                "correction_overlay_applied": True,
            },
        ]


@pytest.mark.parametrize(
    "boolean_field",
    ("initial_capital", "total_value", "last_net_value"),
)
def test_application_facade_keeps_boolean_financial_values_unknown(
    boolean_field: Literal["initial_capital", "total_value", "last_net_value"],
) -> None:
    """A bool cannot become 1.0 through Application normalization and report known."""

    initial_capital = cast(float, True) if boolean_field == "initial_capital" else 1_000.0
    total_value = cast(float, True) if boolean_field == "total_value" else 1.0
    last_net_value = cast(Decimal, True) if boolean_field == "last_net_value" else Decimal("1.00")
    account = SimulatedAccount(
        account_id=41,
        account_name=f"synthetic-boolean-{boolean_field}",
        account_type=AccountType.SIMULATED,
        initial_capital=initial_capital,
        current_cash=1.0,
        current_market_value=0.0,
        total_value=total_value,
        start_date=date(2026, 10, 1),
    )
    posting = FeeCorrectionCashPosting(
        event=FeeCorrectionCashEvent(
            event_id=41,
            posting_date=date(2026, 10, 2),
            posted_at=datetime(2026, 10, 2, 1, tzinfo=UTC),
            cash_delta=Decimal("1.00"),
        ),
        account_revision=1,
        account_prefix_sha256="a" * 64,
    )
    use_case = GetAccountPerformanceUseCase(
        cast(SimulatedAccountRepositoryProtocol, _BooleanAccountRepository(account)),
        cast(PositionRepositoryProtocol, _NoPositionsRepository()),
        cast(TradeRepositoryProtocol, _CorrectionHistoryRepository(posting)),
        cast(DailyNetValueRepositoryProtocol, _BooleanDailyRepository(last_net_value)),
    )

    result = use_case.execute(41)

    assert result["performance_metrics_known"] is False
    assert result["performance_source"] == "unknown"
    assert result["performance_reason_code"] == "FEE_CORRECTION_PERFORMANCE_HISTORY_UNKNOWN"
    assert result["performance"]["total_return"] is None
    assert result["performance"]["annual_return"] is None
    assert result["performance"]["max_drawdown"] is None
    assert result["performance"]["sharpe_ratio"] is None
