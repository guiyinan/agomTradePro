"""
Correlation Calculation Module.

Provides rolling correlation and covariance calculations for financial assets.
Uses NumPy for performance.

Architecture: Infrastructure layer (uses NumPy for computation)
Domain layer interfaces: Pure Python types
"""

import importlib.util
from typing import Any

from shared.domain.correlation import (
    CorrelationMatrix,
    RollingCorrelationCalculator,
)


def try_use_numpy() -> bool:
    """Try to import numpy for optimized calculations"""
    return importlib.util.find_spec("numpy") is not None


class NumPyCorrelationCalculator:
    """
    NumPy-optimized correlation calculator.

    Falls back to pure Python if NumPy is not available.
    """

    def __init__(self) -> None:
        self._use_numpy = try_use_numpy()
        self.np: Any | None = None
        self.fallback: RollingCorrelationCalculator | None = None
        if self._use_numpy:
            import numpy as np

            self.np = np
        else:
            self.fallback = RollingCorrelationCalculator()

    def calculate_correlation_matrix(
        self,
        price_dict: dict[str, list[float]],
        window: int | None = None,
    ) -> CorrelationMatrix:
        """Calculate correlation matrix using NumPy if available"""
        if not self._use_numpy:
            if self.fallback is None:
                raise RuntimeError("Correlation fallback is not initialized")
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
            window_days=window or len(next(iter(prices.values()))),
        )
