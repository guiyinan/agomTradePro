"""Pure formulas for fee-correction-aware account performance metrics."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import TypeGuard

from .services import PerformanceCalculatorService


@dataclass(frozen=True, slots=True)
class CorrectedAccountPerformanceInput:
    """Known daily-history values needed to calculate corrected account metrics."""

    initial_capital: float | None
    final_net_value: float | None
    elapsed_days: int
    drawdowns: tuple[float | None, ...]
    daily_returns_percent: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class CorrectedAccountPerformanceMetrics:
    """Finite cumulative, annualized, drawdown, and Sharpe results."""

    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float


def _is_finite_float(value: object) -> TypeGuard[float]:
    """Reject unknown, non-float, and non-finite values before arithmetic."""

    return type(value) is float and isfinite(value)


def calculate_corrected_account_performance_metrics(
    inputs: CorrectedAccountPerformanceInput,
) -> CorrectedAccountPerformanceMetrics | None:
    """Apply the established corrected-history formulas or return unknown.

    Annual return uses a 365-day exponent. Sharpe uses sample standard deviation
    and the existing Domain trading-day and risk-free-rate constants to preserve
    the account snapshot correction contract without duplicating those settings.
    """

    initial_capital = inputs.initial_capital
    final_net_value = inputs.final_net_value
    if (
        not _is_finite_float(initial_capital)
        or not _is_finite_float(final_net_value)
        or type(inputs.elapsed_days) is not int
        or inputs.elapsed_days <= 0
        or initial_capital <= 0.0
        or not inputs.drawdowns
        or any(not _is_finite_float(value) for value in inputs.drawdowns)
        or len(inputs.daily_returns_percent) < 2
        or any(not _is_finite_float(value) for value in inputs.daily_returns_percent)
    ):
        return None

    try:
        total_return = (final_net_value - initial_capital) / initial_capital * 100.0
        growth_factor = 1.0 + total_return / 100.0
        annual_return = (
            -100.0
            if growth_factor <= 0.0
            else (growth_factor ** (365.0 / inputs.elapsed_days) - 1.0) * 100.0
        )
        daily_returns = tuple(
            value / 100.0 for value in inputs.daily_returns_percent if value is not None
        )
        mean_return = statistics.mean(daily_returns)
        volatility = statistics.stdev(daily_returns)
        if not isfinite(volatility) or volatility <= 0.0:
            return None
        trading_days = PerformanceCalculatorService.TRADING_DAYS_PER_YEAR
        risk_free_rate = PerformanceCalculatorService.RISK_FREE_RATE
        sharpe_ratio = (mean_return * trading_days - risk_free_rate) / (
            volatility * sqrt(trading_days)
        )
        max_drawdown = max(value for value in inputs.drawdowns if value is not None)
    except (ArithmeticError, statistics.StatisticsError, ValueError):
        return None

    metrics = (total_return, annual_return, max_drawdown, sharpe_ratio)
    if any(not isfinite(value) for value in metrics):
        return None
    return CorrectedAccountPerformanceMetrics(
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
    )


__all__ = [
    "CorrectedAccountPerformanceInput",
    "CorrectedAccountPerformanceMetrics",
    "calculate_corrected_account_performance_metrics",
]
