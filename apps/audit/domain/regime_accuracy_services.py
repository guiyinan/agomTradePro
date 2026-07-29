"""Regime accuracy and information-ratio audit services."""

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import NotRequired, Protocol, TypedDict

from apps.backtest.domain.entities import Trade

from .entities import AttributionConfig


class BacktestResultLike(Protocol):
    """Minimal backtest result surface required by attribution calculations."""

    @property
    def equity_curve(self) -> Sequence[tuple[date, float]]: ...

    @property
    def trades(self) -> Sequence[Trade]: ...

    @property
    def total_return(self) -> float: ...


class RegimeAccuracyResult(TypedDict):
    """Serializable Regime accuracy metrics."""

    total_periods: int
    correct_predictions: int
    accuracy: float
    regime_confusion_matrix: NotRequired[dict[str, dict[str, int]]]


class AttributionAnalyzer:
    """Analyze Regime classification accuracy and active returns."""

    def __init__(self, config: AttributionConfig | None = None) -> None:
        self.config = config or AttributionConfig()

    def analyze_regime_accuracy(
        self,
        regime_history: Sequence[Mapping[str, object]],
        actual_regime_history: Sequence[Mapping[str, object]],
    ) -> RegimeAccuracyResult:
        """Compare predicted and actual Regime observations."""
        if not regime_history or not actual_regime_history:
            return {"total_periods": 0, "correct_predictions": 0, "accuracy": 0.0}

        aligned = self._align_regime_observations(regime_history, actual_regime_history)
        correct = sum(
            1 for predicted, actual in aligned if predicted.casefold() == actual.casefold()
        )
        total = len(aligned)
        return {
            "total_periods": total,
            "correct_predictions": correct,
            "accuracy": correct / total if total > 0 else 0.0,
            "regime_confusion_matrix": self._build_confusion_matrix(
                regime_history,
                actual_regime_history,
            ),
        }

    @staticmethod
    def _align_regime_observations(
        predicted: Sequence[Mapping[str, object]],
        actual: Sequence[Mapping[str, object]],
    ) -> list[tuple[str, str]]:
        """Align observations by date when dates exist, otherwise by position."""
        predicted_by_date = {
            entry_date: regime
            for entry in predicted
            if isinstance((entry_date := entry.get("date")), date)
            and isinstance((regime := entry.get("regime")), str)
            and regime.strip()
        }
        actual_by_date = {
            entry_date: regime
            for entry in actual
            if isinstance((entry_date := entry.get("date")), date)
            and isinstance((regime := entry.get("regime")), str)
            and regime.strip()
        }
        if predicted_by_date and actual_by_date:
            common_dates = sorted(predicted_by_date.keys() & actual_by_date.keys())
            return [
                (predicted_by_date[entry_date], actual_by_date[entry_date])
                for entry_date in common_dates
            ]

        aligned: list[tuple[str, str]] = []
        for predicted_entry, actual_entry in zip(predicted, actual, strict=False):
            predicted_regime = predicted_entry.get("regime")
            actual_regime = actual_entry.get("regime")
            if (
                isinstance(predicted_regime, str)
                and predicted_regime.strip()
                and isinstance(actual_regime, str)
                and actual_regime.strip()
            ):
                aligned.append((predicted_regime, actual_regime))
        return aligned

    def _build_confusion_matrix(
        self,
        predicted: Sequence[Mapping[str, object]],
        actual: Sequence[Mapping[str, object]],
    ) -> dict[str, dict[str, int]]:
        """Build a canonical four-Regime confusion matrix."""
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]
        canonical = {regime.casefold(): regime for regime in regimes}
        matrix: dict[str, dict[str, int]] = {
            regime: dict.fromkeys(regimes, 0) for regime in regimes
        }
        for predicted_regime, actual_regime in self._align_regime_observations(predicted, actual):
            predicted_label = canonical.get(predicted_regime.casefold())
            actual_label = canonical.get(actual_regime.casefold())
            if predicted_label is not None and actual_label is not None:
                matrix[predicted_label][actual_label] += 1
        return matrix

    def calculate_information_ratio(
        self,
        backtest_result: BacktestResultLike,
        benchmark_returns: Sequence[float],
    ) -> float | None:
        """Calculate annualized active return per unit of tracking error."""
        equity_curve = backtest_result.equity_curve
        interval_count = len(equity_curve) - 1
        if interval_count < 1 or len(benchmark_returns) != interval_count:
            return None

        excess_returns: list[float] = []
        for index in range(1, len(equity_curve)):
            previous_value = equity_curve[index - 1][1]
            current_value = equity_curve[index][1]
            benchmark_return = benchmark_returns[index - 1]
            if (
                not math.isfinite(previous_value)
                or not math.isfinite(current_value)
                or not math.isfinite(benchmark_return)
                or previous_value <= 0
            ):
                return None
            portfolio_return = (current_value - previous_value) / previous_value
            excess_returns.append(portfolio_return - benchmark_return)

        mean_excess = sum(excess_returns) / len(excess_returns)
        variance = sum(
            (active_return - mean_excess) ** 2 for active_return in excess_returns
        ) / len(excess_returns)
        standard_deviation = math.sqrt(variance)
        if standard_deviation == 0:
            return None
        return mean_excess * 252 / (standard_deviation * math.sqrt(252))


__all__ = ["AttributionAnalyzer"]
