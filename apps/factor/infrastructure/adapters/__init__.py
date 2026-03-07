"""
Factor Module Infrastructure Layer - Data Adapters

Fetches factor data for stocks (PE, PB, ROE, etc.)
Implements failover between data sources.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


class FactorDataSource:
    """Factor data source adapter"""

    def get_factor_value(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get factor value for a stock on a date"""
        raise NotImplementedError


class TushareFactorAdapter(FactorDataSource):
    """Tushare factor data adapter"""

    def __init__(self):
        self._pro = None
        self._connected = False

    def _connect(self):
        """Connect to Tushare"""
        if self._connected:
            return

        try:
            import tushare as ts
            from shared.config.secrets import get_secrets
            secrets = get_secrets()
            token = secrets.data_sources.tushare_token
            self._pro = ts.pro_api(token)
            self._connected = True
        except Exception as e:
            logger.warning(f"Failed to connect to Tushare: {e}")
            self._connected = False

    def get_factor_value(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get factor value from Tushare"""
        self._connect()

        if not self._connected or not self._pro:
            return None

        try:
            ts_code = self._convert_to_tushare_code(stock_code)

            # Map factor codes to Tushare API calls
            if factor_code in ['pe_ttm', 'pb', 'ps']:
                return self._get_valuation_factor(ts_code, factor_code, trade_date)
            elif factor_code in ['roe', 'roa', 'current_ratio', 'debt_ratio']:
                return self._get_financial_factor(ts_code, factor_code, trade_date)
            elif factor_code in ['revenue_growth', 'profit_growth']:
                return self._get_growth_factor(ts_code, factor_code, trade_date)
            elif factor_code in ['dividend_yield']:
                return self._get_dividend_factor(ts_code, trade_date)
            elif factor_code.startswith('momentum_'):
                return None  # Calculated from price data
            elif factor_code.startswith('volatility_'):
                return None  # Calculated from price data
            else:
                logger.warning(f"Unknown factor code: {factor_code}")
                return None

        except Exception as e:
            logger.warning(f"Failed to fetch {factor_code} for {stock_code}: {e}")
            return None

    def _get_valuation_factor(
        self,
        ts_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get valuation factor (PE, PB, PS)"""
        # Get daily basic data
        end_date = trade_date.strftime('%Y%m%d')
        start_date = (trade_date - timedelta(days=10)).strftime('%Y%m%d')

        df = self._pro.daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,pe_ttm,pb,ps,dv_ratio'
        )

        if df is None or df.empty:
            return None

        # Get most recent data
        df = df.sort_values('trade_date').iloc[-1]

        factor_map = {
            'pe_ttm': 'pe_ttm',
            'pb': 'pb',
            'ps': 'ps',
            'dividend_yield': 'dv_ratio',
        }

        field = factor_map.get(factor_code)
        if field and field in df:
            value = df[field]
            return float(value) if value is not None and not pd.isna(value) else None

        return None

    def _get_financial_factor(
        self,
        ts_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get financial factor (ROE, ROA, etc.)"""
        import pandas as pd

        # Get latest financial data
        df = self._pro.income(
            ts_code=ts_code,
            start_date=(trade_date - timedelta(days=400)).strftime('%Y%m%d'),
            end_date=trade_date.strftime('%Y%m%d'),
            fields='end_date,roe,roa,current_ratio,debt_to_assets'
        )

        if df is None or df.empty:
            return None

        # Get most recent report
        df = df.sort_values('end_date').iloc[-1]

        factor_map = {
            'roe': 'roe',
            'roa': 'roa',
            'current_ratio': 'current_ratio',
            'debt_ratio': 'debt_to_assets',
        }

        field = factor_map.get(factor_code)
        if field and field in df:
            value = df[field]
            return float(value) if value is not None and not pd.isna(value) else None

        return None

    def _get_growth_factor(
        self,
        ts_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get growth factor (revenue_growth, profit_growth)"""
        import pandas as pd

        # Get growth data
        df = self._pro.fina_growth_type(
            ts_code=ts_code,
            start_date=(trade_date - timedelta(days=400)).strftime('%Y%m%d'),
            end_date=trade_date.strftime('%Y%m%d'),
            fields='end_date,or_yoy,netprofit_yoy'
        )

        if df is None or df.empty:
            return None

        # Get most recent report
        df = df.sort_values('end_date').iloc[-1]

        factor_map = {
            'revenue_growth': 'or_yoy',
            'profit_growth': 'netprofit_yoy',
        }

        field = factor_map.get(factor_code)
        if field and field in df:
            value = df[field]
            # Convert percentage to decimal
            return float(value) / 100 if value is not None and not pd.isna(value) else None

        return None

    def _get_dividend_factor(
        self,
        ts_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get dividend yield"""
        return self._get_valuation_factor(ts_code, 'dividend_yield', trade_date)

    def _convert_to_tushare_code(self, stock_code: str) -> str:
        """Convert stock code to Tushare format"""
        if len(stock_code) == 6:
            if stock_code.startswith('6'):
                return f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                return f"{stock_code}.SZ"
        return stock_code


class AkshareFactorAdapter(FactorDataSource):
    """Akshare factor data adapter (backup source)"""

    def get_factor_value(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get factor value from Akshare"""
        try:
            import akshare as ak

            if factor_code in ['pe_ttm', 'pb']:
                return self._get_valuation_akshare(stock_code, factor_code)
            elif factor_code in ['roe', 'revenue_growth']:
                return self._get_financial_akshare(stock_code, factor_code)
            else:
                return None

        except Exception as e:
            logger.warning(f"Akshare failed for {stock_code} {factor_code}: {e}")
            return None

    def _get_valuation_akshare(self, stock_code: str, factor_code: str) -> Optional[float]:
        """Get valuation from Akshare"""
        import akshare as ak

        symbol = self._convert_to_akshare_symbol(stock_code)
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")

        if df is not None and not df.empty:
            # Get most recent data
            df = df.tail(60)

            if factor_code == 'pe_ttm':
                # Simple PE calculation using recent data
                if '收盘' in df.columns:
                    # Use TTM logic or latest available
                    # For simplicity, use a placeholder
                    return None

            elif factor_code == 'pb':
                return None

        return None

    def _get_financial_akshare(self, stock_code: str, factor_code: str) -> Optional[float]:
        """Get financial data from Akshare"""
        # Implementation for financial factors
        return None

    def _convert_to_akshare_symbol(self, stock_code: str) -> str:
        """Convert stock code to Akshare format"""
        if len(stock_code) == 6:
            return stock_code
        return stock_code


class CachedFactorAdapter(FactorDataSource):
    """Cached factor adapter with price-based calculations"""

    def __init__(self, price_adapter=None):
        from apps.rotation.infrastructure.adapters.price_adapter import RotationPriceDataService
        self.price_service = price_adapter or RotationPriceDataService()
        self._cache = {}

    def get_factor_value(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Get factor value, calculate from prices if needed"""
        # Check cache first
        cache_key = f"{stock_code}_{factor_code}_{trade_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Calculate momentum/volatility factors from prices
        if factor_code.startswith('momentum_') or factor_code.startswith('volatility_'):
            return self._calculate_from_prices(stock_code, factor_code, trade_date)

        # For fundamental factors, return None (will be fetched from other adapters)
        return None

    def _calculate_from_prices(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
        """Calculate factor from price data"""
        try:
            from apps.account.infrastructure.models import SystemSettingsModel

            # Determine period from factor code
            if '1m' in factor_code:
                days = 20
            elif '3m' in factor_code:
                days = 60
            elif '6m' in factor_code:
                days = 120
            elif '12m' in factor_code:
                days = 252
            else:
                days = 60

            prices = self.price_service.get_prices(stock_code, trade_date, days + 10)

            if not prices or len(prices) < days:
                return None

            if factor_code.startswith('momentum_'):
                return self._calculate_momentum(prices, days)
            elif factor_code.startswith('volatility_'):
                return self._calculate_volatility(prices, days)
            elif factor_code == 'beta':
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

    def _calculate_momentum(self, prices: List[float], days: int) -> float:
        """Calculate momentum return"""
        if len(prices) < days + 1:
            return 0.0

        current = prices[-1]
        past = prices[-(days + 1)]

        return (current - past) / past if past > 0 else 0.0

    def _calculate_volatility(self, prices: List[float], days: int) -> float:
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
        self,
        asset_prices: List[float],
        benchmark_prices: List[float],
        days: int
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
                benchmark_returns.append((benchmark_prices[i] - benchmark_prices[i - 1]) / benchmark_prices[i - 1])

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

    def get_factor_value(
        self,
        stock_code: str,
        factor_code: str,
        trade_date: date
    ) -> Optional[float]:
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
