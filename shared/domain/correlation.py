"""
Shared domain correlation algorithms.

Pure Python correlation and covariance calculations that can be reused by
domain services without depending on infrastructure packages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelationResult:
    """Correlation calculation result."""

    asset1: str
    asset2: str
    correlation: float
    covariance: float
    window_days: int
    start_date: str
    end_date: str
    sample_size: int


@dataclass(frozen=True)
class CorrelationMatrix:
    """Correlation matrix for multiple assets."""

    assets: list[str]
    matrix: list[list[float]]
    calc_date: str
    window_days: int

    def get_correlation(self, asset1: str, asset2: str) -> float | None:
        """Return correlation between two assets when both are present."""

        try:
            idx1 = self.assets.index(asset1)
            idx2 = self.assets.index(asset2)
            return self.matrix[idx1][idx2]
        except (ValueError, IndexError):
            return None


class RollingCorrelationCalculator:
    """Pure Python rolling correlation calculator."""

    def calculate_rolling_correlation(
        self,
        prices1: list[float],
        prices2: list[float],
        window: int = 20,
    ) -> list[float | None]:
        """Calculate rolling correlation coefficients."""

        if len(prices1) != len(prices2):
            raise ValueError("Price series must have same length")

        if len(prices1) < window:
            return [None] * len(prices1)

        returns1 = self._calculate_returns(prices1)
        returns2 = self._calculate_returns(prices2)

        correlations: list[float | None] = []
        for i in range(len(returns1)):
            if i < window:
                correlations.append(None)
                continue

            window_returns1 = returns1[i - window + 1 : i + 1]
            window_returns2 = returns2[i - window + 1 : i + 1]
            correlations.append(
                self._correlation_coefficient(window_returns1, window_returns2)
            )

        return correlations

    def calculate_correlation(
        self,
        prices1: list[float],
        prices2: list[float],
    ) -> float:
        """Calculate correlation over the full period."""

        if len(prices1) != len(prices2):
            raise ValueError("Price series must have same length")
        if len(prices1) < 2:
            raise ValueError("Need at least 2 data points")

        returns1 = self._calculate_returns(prices1)
        returns2 = self._calculate_returns(prices2)
        return self._correlation_coefficient(returns1, returns2)

    def calculate_covariance(
        self,
        prices1: list[float],
        prices2: list[float],
    ) -> float:
        """Calculate covariance between two price series."""

        if len(prices1) != len(prices2):
            raise ValueError("Price series must have same length")
        if len(prices1) < 2:
            raise ValueError("Need at least 2 data points")

        returns1 = self._calculate_returns(prices1)
        returns2 = self._calculate_returns(prices2)

        n = len(returns1)
        mean1 = sum(returns1) / n
        mean2 = sum(returns2) / n
        return sum(
            (r1 - mean1) * (r2 - mean2)
            for r1, r2 in zip(returns1, returns2, strict=True)
        ) / (n - 1)

    def calculate_correlation_matrix(
        self,
        price_dict: dict[str, list[float]],
        window: int | None = None,
    ) -> CorrelationMatrix:
        """Calculate a symmetric correlation matrix."""

        assets = list(price_dict.keys())
        size = len(assets)
        prices = {k: v[-window:] for k, v in price_dict.items()} if window else price_dict
        matrix = [[0.0] * size for _ in range(size)]

        for i in range(size):
            for j in range(size):
                if i == j:
                    matrix[i][j] = 1.0
                elif i < j:
                    corr = self.calculate_correlation(prices[assets[i]], prices[assets[j]])
                    matrix[i][j] = corr
                    matrix[j][i] = corr

        return CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            calc_date="",
            window_days=window or len(next(iter(prices.values()))),
        )

    def calculate_beta(
        self,
        asset_prices: list[float],
        benchmark_prices: list[float],
    ) -> float:
        """Calculate beta of one asset relative to a benchmark."""

        if len(asset_prices) != len(benchmark_prices):
            raise ValueError("Price series must have same length")
        if len(asset_prices) < 2:
            raise ValueError("Need at least 2 data points")

        asset_returns = self._calculate_returns(asset_prices)
        benchmark_returns = self._calculate_returns(benchmark_prices)
        n = len(asset_returns)

        mean_asset = sum(asset_returns) / n
        mean_benchmark = sum(benchmark_returns) / n
        covariance = sum(
            (ra - mean_asset) * (rb - mean_benchmark)
            for ra, rb in zip(asset_returns, benchmark_returns, strict=True)
        ) / (n - 1)
        variance = sum((rb - mean_benchmark) ** 2 for rb in benchmark_returns) / (n - 1)

        if variance == 0:
            return 0.0
        return covariance / variance

    def _calculate_returns(self, prices: list[float]) -> list[float]:
        """Calculate simple returns from price series."""

        returns: list[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
            else:
                returns.append(0.0)
        return returns

    def _correlation_coefficient(self, x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation coefficient."""

        n = len(x)
        if n < 2:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=True))
        sum_xx = sum((xi - mean_x) ** 2 for xi in x)
        sum_yy = sum((yi - mean_y) ** 2 for yi in y)
        denominator = (sum_xx * sum_yy) ** 0.5

        if denominator == 0:
            return 0.0
        return numerator / denominator
