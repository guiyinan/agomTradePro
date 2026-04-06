"""
Factor Module Infrastructure Layer - Data Adapters

Fetches factor data for stocks (PE, PB, ROE, etc.)
Implements failover between data sources.
"""

import logging
from datetime import date

from apps.data_center.infrastructure.models import FinancialFactModel, ValuationFactModel

logger = logging.getLogger(__name__)


class FactorDataSource:
    """Factor data source adapter"""

    def get_factor_value(self, stock_code: str, factor_code: str, trade_date: date) -> float | None:
        """Get factor value for a stock on a date"""
        raise NotImplementedError


class TushareFactorAdapter(FactorDataSource):
    """Tushare factor data adapter"""

    def __init__(self):
        self._connected = True

    def get_factor_value(self, stock_code: str, factor_code: str, trade_date: date) -> float | None:
        return _get_factor_from_data_center(stock_code, factor_code, trade_date, source_hint="tushare")


class AkshareFactorAdapter(FactorDataSource):
    """Akshare factor data adapter (backup source)"""

    def get_factor_value(self, stock_code: str, factor_code: str, trade_date: date) -> float | None:
        return _get_factor_from_data_center(stock_code, factor_code, trade_date, source_hint="akshare")


def _get_factor_from_data_center(
    stock_code: str,
    factor_code: str,
    trade_date: date,
    source_hint: str,
) -> float | None:
    valuation_field_map = {
        "pe_ttm": "pe_ttm",
        "pb": "pb",
        "ps": "ps_ttm",
        "dividend_yield": "dv_ratio",
    }
    financial_metric_map = {
        "roe": "roe",
        "roa": "roa",
        "debt_ratio": "debt_ratio",
        "revenue_growth": "revenue_growth",
        "profit_growth": "net_profit_growth",
    }

    if factor_code in valuation_field_map:
        qs = ValuationFactModel.objects.filter(asset_code=stock_code, val_date__lte=trade_date)
        if source_hint:
            qs = qs.filter(source__icontains=source_hint)
        row = qs.order_by("-val_date").first()
        if row is None:
            return None
        value = getattr(row, valuation_field_map[factor_code], None)
        return float(value) if value is not None else None

    if factor_code in financial_metric_map:
        qs = FinancialFactModel.objects.filter(
            asset_code=stock_code,
            metric_code=financial_metric_map[factor_code],
            period_end__lte=trade_date,
        )
        if source_hint:
            qs = qs.filter(source__icontains=source_hint)
        row = qs.order_by("-period_end").first()
        return float(row.value) if row is not None else None

    return None


class CachedFactorAdapter(FactorDataSource):
    """Cached factor adapter with price-based calculations"""

    def __init__(self, price_adapter=None):
        from apps.rotation.infrastructure.adapters.price_adapter import RotationPriceDataService

        self.price_service = price_adapter or RotationPriceDataService()
        self._cache = {}

    def get_factor_value(self, stock_code: str, factor_code: str, trade_date: date) -> float | None:
        """Get factor value, calculate from prices if needed"""
        # Check cache first
        cache_key = f"{stock_code}_{factor_code}_{trade_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Calculate momentum/volatility factors from prices
        if factor_code.startswith("momentum_") or factor_code.startswith("volatility_"):
            return self._calculate_from_prices(stock_code, factor_code, trade_date)

        # For fundamental factors, return None (will be fetched from other adapters)
        return None

    def _calculate_from_prices(
        self, stock_code: str, factor_code: str, trade_date: date
    ) -> float | None:
        """Calculate factor from price data"""
        try:
            from apps.account.infrastructure.models import SystemSettingsModel

            # Determine period from factor code
            if "1m" in factor_code:
                days = 20
            elif "3m" in factor_code:
                days = 60
            elif "6m" in factor_code:
                days = 120
            elif "12m" in factor_code:
                days = 252
            else:
                days = 60

            prices = self.price_service.get_prices(stock_code, trade_date, days + 10)

            if not prices or len(prices) < days:
                return None

            if factor_code.startswith("momentum_"):
                return self._calculate_momentum(prices, days)
            elif factor_code.startswith("volatility_"):
                return self._calculate_volatility(prices, days)
            elif factor_code == "beta":
                benchmark_code = SystemSettingsModel.get_runtime_benchmark_code(
                    "factor_beta_benchmark"
                )
                if not benchmark_code:
                    return None
                benchmark_prices = self.price_service.get_prices(benchmark_code, trade_date, days)
                if benchmark_prices:
                    return self._calculate_beta(prices, benchmark_prices, days)

        except Exception as e:
            logger.warning(f"Failed to calculate {factor_code} for {stock_code}: {e}")

        return None

    def _calculate_momentum(self, prices: list[float], days: int) -> float:
        """Calculate momentum return"""
        if len(prices) < days + 1:
            return 0.0

        current = prices[-1]
        past = prices[-(days + 1)]

        return (current - past) / past if past > 0 else 0.0

    def _calculate_volatility(self, prices: list[float], days: int) -> float:
        """Calculate volatility (annualized std)"""
        import math

        if len(prices) < days:
            return 0.0

        window_prices = prices[-days:]

        # Calculate returns
        returns = []
        for i in range(1, len(window_prices)):
            if window_prices[i - 1] > 0:
                ret = (window_prices[i] - window_prices[i - 1]) / window_prices[i - 1]
                returns.append(ret)

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance)

        # Annualize
        return std * math.sqrt(252)

    def _calculate_beta(
        self, asset_prices: list[float], benchmark_prices: list[float], days: int
    ) -> float:
        """Calculate beta to benchmark"""
        if len(asset_prices) < days or len(benchmark_prices) < days:
            return 1.0

        asset_prices = asset_prices[-days:]
        benchmark_prices = benchmark_prices[-days:]

        # Calculate returns
        asset_returns = []
        benchmark_returns = []

        for i in range(1, len(asset_prices)):
            if asset_prices[i - 1] > 0:
                asset_returns.append((asset_prices[i] - asset_prices[i - 1]) / asset_prices[i - 1])

        for i in range(1, len(benchmark_prices)):
            if benchmark_prices[i - 1] > 0:
                benchmark_returns.append(
                    (benchmark_prices[i] - benchmark_prices[i - 1]) / benchmark_prices[i - 1]
                )

        if len(asset_returns) != len(benchmark_returns):
            return 1.0

        n = len(asset_returns)

        # Calculate covariance and variance
        mean_asset = sum(asset_returns) / n
        mean_benchmark = sum(benchmark_returns) / n

        covariance = sum(
            (a - mean_asset) * (b - mean_benchmark)
            for a, b in zip(asset_returns, benchmark_returns)
        ) / (n - 1)

        variance = sum((b - mean_benchmark) ** 2 for b in benchmark_returns) / (n - 1)

        return covariance / variance if variance > 0 else 1.0


class FailoverFactorAdapter(FactorDataSource):
    """Failover factor adapter with multiple data sources"""

    def __init__(self):
        self.primary_adapter = TushareFactorAdapter()
        self.secondary_adapter = AkshareFactorAdapter()
        self.cached_adapter = CachedFactorAdapter()

    def get_factor_value(self, stock_code: str, factor_code: str, trade_date: date) -> float | None:
        """Get factor value with failover"""
        # Try price-based factors first (fastest)
        value = self.cached_adapter.get_factor_value(stock_code, factor_code, trade_date)
        if value is not None:
            return value

        # Try primary adapter (Tushare)
        value = self.primary_adapter.get_factor_value(stock_code, factor_code, trade_date)
        if value is not None:
            return value

        # Try secondary adapter (Akshare)
        value = self.secondary_adapter.get_factor_value(stock_code, factor_code, trade_date)
        if value is not None:
            return value

        return None
