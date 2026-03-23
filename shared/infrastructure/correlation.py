"""
Correlation Calculation Module.

Provides rolling correlation and covariance calculations for financial assets.
Uses NumPy for performance.

Architecture: Infrastructure layer (uses NumPy for computation)
Domain layer interfaces: Pure Python types
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple


@dataclass
class CorrelationResult:
    """Correlation calculation result (Domain entity)"""
    asset1: str
    asset2: str
    correlation: float
    covariance: float
    window_days: int
    start_date: str  # ISO format date string
    end_date: str    # ISO format date string
    sample_size: int  # Actual number of data points used


@dataclass
class CorrelationMatrix:
    """Correlation matrix for multiple assets (Domain entity)"""
    assets: list[str]
    matrix: list[list[float]]  # Square matrix of correlations
    calc_date: str  # ISO format date string
    window_days: int

    def get_correlation(self, asset1: str, asset2: str) -> float | None:
        """Get correlation between two assets"""
        try:
            idx1 = self.assets.index(asset1)
            idx2 = self.assets.index(asset2)
            return self.matrix[idx1][idx2]
        except (ValueError, IndexError):
            return None


class RollingCorrelationCalculator:
    """
    Rolling correlation calculator using pure Python.

    This is the Infrastructure layer implementation that can use NumPy
    for performance. The Domain layer defines the interfaces.
    """

    def __init__(self):
        pass

    def calculate_rolling_correlation(
        self,
        prices1: list[float],
        prices2: list[float],
        window: int = 20
    ) -> list[float | None]:
        """
        Calculate rolling correlation coefficient.

        Args:
            prices1: Price series for asset 1
            prices2: Price series for asset 2
            window: Rolling window size (default: 20 days)

        Returns:
            List of correlation values (None where insufficient data)
        """
        if len(prices1) != len(prices2):
            raise ValueError("Price series must have same length")

        if len(prices1) < window:
            return [None] * len(prices1)

        # Calculate returns
        returns1 = self._calculate_returns(prices1)
        returns2 = self._calculate_returns(prices2)

        correlations = []
        for i in range(len(returns1)):
            if i < window:
                correlations.append(None)
            else:
                window_returns1 = returns1[i-window+1:i+1]
                window_returns2 = returns2[i-window+1:i+1]

                corr = self._correlation_coefficient(window_returns1, window_returns2)
                correlations.append(corr)

        return correlations

    def calculate_correlation(
        self,
        prices1: list[float],
        prices2: list[float]
    ) -> float:
        """
        Calculate single correlation coefficient over entire period.

        Args:
            prices1: Price series for asset 1
            prices2: Price series for asset 2

        Returns:
            Correlation coefficient (-1 to 1)
        """
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
        prices2: list[float]
    ) -> float:
        """
        Calculate covariance between two price series.

        Args:
            prices1: Price series for asset 1
            prices2: Price series for asset 2

        Returns:
            Covariance value
        """
        if len(prices1) != len(prices2):
            raise ValueError("Price series must have same length")

        if len(prices1) < 2:
            raise ValueError("Need at least 2 data points")

        returns1 = self._calculate_returns(prices1)
        returns2 = self._calculate_returns(prices2)

        n = len(returns1)
        mean1 = sum(returns1) / n
        mean2 = sum(returns2) / n

        covariance = sum((r1 - mean1) * (r2 - mean2) for r1, r2 in zip(returns1, returns2)) / (n - 1)

        return covariance

    def calculate_correlation_matrix(
        self,
        price_dict: dict,  # {asset_code: [prices]}
        window: int | None = None
    ) -> CorrelationMatrix:
        """
        Calculate correlation matrix for multiple assets.

        Args:
            price_dict: Dictionary mapping asset codes to price lists
            window: If specified, use last N prices only

        Returns:
            CorrelationMatrix domain entity
        """
        assets = list(price_dict.keys())
        n = len(assets)

        # Truncate to window if specified
        if window:
            prices = {k: v[-window:] for k, v in price_dict.items()}
        else:
            prices = price_dict

        # Build correlation matrix
        matrix = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix[i][j] = 1.0
                elif i < j:  # Only calculate upper triangle
                    corr = self.calculate_correlation(prices[assets[i]], prices[assets[j]])
                    matrix[i][j] = corr
                    matrix[j][i] = corr  # Symmetric

        return CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            calc_date="",  # To be filled by caller
            window_days=window or len(next(iter(prices.values())))
        )

    def _calculate_returns(self, prices: list[float]) -> list[float]:
        """Calculate log returns from price series"""
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)
            else:
                returns.append(0.0)
        return returns

    def _correlation_coefficient(self, x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation coefficient"""
        n = len(x)
        if n < 2:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        # Calculate numerator and denominators
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        sum_xx = sum((xi - mean_x) ** 2 for xi in x)
        sum_yy = sum((yi - mean_y) ** 2 for yi in y)

        denominator = (sum_xx * sum_yy) ** 0.5

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def calculate_beta(
        self,
        asset_prices: list[float],
        benchmark_prices: list[float]
    ) -> float:
        """
        Calculate beta coefficient (asset sensitivity to benchmark).

        Beta = Covariance(asset, benchmark) / Variance(benchmark)

        Args:
            asset_prices: Price series for the asset
            benchmark_prices: Price series for the benchmark

        Returns:
            Beta coefficient
        """
        if len(asset_prices) != len(benchmark_prices):
            raise ValueError("Price series must have same length")

        if len(asset_prices) < 2:
            raise ValueError("Need at least 2 data points")

        # Calculate returns
        asset_returns = self._calculate_returns(asset_prices)
        benchmark_returns = self._calculate_returns(benchmark_prices)

        n = len(asset_returns)

        # Calculate means
        mean_asset = sum(asset_returns) / n
        mean_benchmark = sum(benchmark_returns) / n

        # Calculate covariance and variance
        covariance = sum(
            (ra - mean_asset) * (rb - mean_benchmark)
            for ra, rb in zip(asset_returns, benchmark_returns)
        ) / (n - 1)

        variance = sum((rb - mean_benchmark) ** 2 for rb in benchmark_returns) / (n - 1)

        if variance == 0:
            return 0.0

        return covariance / variance


def try_use_numpy():
    """Try to import numpy for optimized calculations"""
    try:
        import numpy as np
        return True
    except ImportError:
        return False


class NumPyCorrelationCalculator:
    """
    NumPy-optimized correlation calculator.

    Falls back to pure Python if NumPy is not available.
    """

    def __init__(self):
        self._use_numpy = try_use_numpy()
        if self._use_numpy:
            import numpy as np
            self.np = np
        else:
            self.fallback = RollingCorrelationCalculator()

    def calculate_correlation_matrix(
        self,
        price_dict: dict,
        window: int | None = None
    ) -> CorrelationMatrix:
        """Calculate correlation matrix using NumPy if available"""
        if not self._use_numpy:
            return self.fallback.calculate_correlation_matrix(price_dict, window)

        import numpy as np

        assets = list(price_dict.keys())
        n = len(assets)

        # Truncate to window if specified
        if window:
            prices = {k: np.array(v[-window:]) for k, v in price_dict.items()}
        else:
            prices = {k: np.array(v) for k, v in price_dict.items()}

        # Calculate returns
        returns = {}
        for asset, price_array in prices.items():
            ret = np.diff(price_array) / price_array[:-1]
            returns[asset] = ret

        # Build matrix
        matrix_data = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix_data[i][j] = 1.0
                elif i < j:
                    corr = np.corrcoef(returns[assets[i]], returns[assets[j]])[0, 1]
                    # Handle NaN
                    if np.isnan(corr):
                        corr = 0.0
                    matrix_data[i][j] = corr
                    matrix_data[j][i] = corr

        # Convert to list for domain entity
        matrix = matrix_data.tolist()

        return CorrelationMatrix(
            assets=assets,
            matrix=matrix,
            calc_date="",
            window_days=window or len(next(iter(prices.values())))
        )
