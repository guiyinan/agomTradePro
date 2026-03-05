"""
Rotation Module Infrastructure Layer - Price Data Adapter

Fetches price data for ETFs and other assets.
Implements failover between data sources.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional, Dict
import logging

from django.utils import timezone

from shared.config.secrets import get_secrets

logger = logging.getLogger(__name__)


class PriceDataSource:
    """Price data source adapter"""

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int
    ) -> Optional[List[float]]:
        """
        Get historical prices for an asset.

        Args:
            asset_code: Asset code (e.g., "510300" for ETF)
            end_date: End date for price data
            days_back: Number of days of history to fetch

        Returns:
            List of closing prices (oldest to newest) or None if unavailable
        """
        raise NotImplementedError


class TusharePriceAdapter(PriceDataSource):
    """Tushare price data adapter for ETFs and indices"""

    def __init__(self):
        self._pro = None
        self._connected = False

    def _connect(self):
        """Connect to Tushare"""
        if self._connected:
            return

        try:
            import tushare as ts
            secrets = get_secrets()
            token = secrets.data_sources.tushare_token
            self._pro = ts.pro_api(token)
            self._connected = True
        except Exception as e:
            logger.warning(f"Failed to connect to Tushare: {e}")
            self._connected = False

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int
    ) -> Optional[List[float]]:
        """Get prices from Tushare"""
        self._connect()

        if not self._connected or not self._pro:
            return None

        try:
            # Convert ETF code to Tushare format
            ts_code = self._convert_to_tushare_code(asset_code)

            # Calculate start date
            start_date = end_date - timedelta(days=days_back + 30)  # Add buffer for non-trading days

            # Fetch data
            df = self._pro.fund_daily(
                ts_code=ts_code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )

            if df is None or df.empty:
                # Try as index
                df = self._pro.index_daily(
                    ts_code=ts_code,
                    start_date=start_date.strftime('%Y%m%d'),
                    end_date=end_date.strftime('%Y%m%d')
                )

            if df is None or df.empty:
                return None

            # Sort by date and get close prices
            df = df.sort_values('trade_date')
            prices = df['close'].tolist()

            # Return last `days_back` prices
            return prices[-days_back:] if len(prices) > days_back else prices

        except Exception as e:
            logger.warning(f"Failed to fetch prices for {asset_code} from Tushare: {e}")
            return None

    def _convert_to_tushare_code(self, asset_code: str) -> str:
        """Convert asset code to Tushare format"""
        # ETF codes in China: 5xxxxx.SH or 15xxxx.SZ
        if asset_code.startswith('51') or asset_code.startswith('15'):
            if asset_code.startswith('56') or asset_code.startswith('58'):
                # Shanghai ETF
                return f"{asset_code}.SH"
            else:
                # Shenzhen ETF
                return f"{asset_code}.SZ"
        return asset_code


class AksharePriceAdapter(PriceDataSource):
    """Akshare price data adapter (backup source)"""

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int
    ) -> Optional[List[float]]:
        """Get prices from Akshare"""
        try:
            import akshare as ak

            # Calculate start date
            start_date = end_date - timedelta(days=days_back + 30)

            # Determine asset type and fetch accordingly
            if asset_code.startswith('51') or asset_code.startswith('15'):
                # ETF
                df = ak.fund_etf_hist_sina(symbol=asset_code)
            elif asset_code.startswith('00') or asset_code.startswith('30'):
                # Stock index
                df = ak.stock_zh_index_daily(symbol=f"sh{asset_code}")
            else:
                return None

            if df is None or df.empty:
                return None

            # Filter by date range and get close prices
            try:
                import pandas as pd
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
                df = df.sort_values('date')

                prices = df['close'].tolist()

                return prices[-days_back:] if len(prices) > days_back else prices
            except ImportError:
                # Fallback without pandas
                dates = df['date'].tolist()
                closes = df['close'].tolist()

                # Simple filter
                filtered = [
                    close for date_val, close in zip(dates, closes)
                    if start_date <= date_val <= end_date
                ]

                return filtered[-days_back:] if len(filtered) > days_back else filtered

        except Exception as e:
            logger.warning(f"Failed to fetch prices for {asset_code} from Akshare: {e}")
            return None


class MockPriceAdapter(PriceDataSource):
    """Mock price adapter for testing/development"""

    def __init__(self):
        # Store mock prices
        self._mock_prices: Dict[str, List[float]] = {}

    def set_mock_prices(self, asset_code: str, prices: List[float]):
        """Set mock prices for an asset"""
        self._mock_prices[asset_code] = prices

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int
    ) -> Optional[List[float]]:
        """Get mock prices"""
        if asset_code not in self._mock_prices:
            # Generate synthetic price data
            import random
            base_price = 3.0  # Base price for most ETFs
            prices = []
            price = base_price

            for _ in range(days_back):
                # Random walk with slight upward drift
                change = random.gauss(0.0002, 0.015)  # Daily return ~ N(0.02%, 1.5%)
                price = price * (1 + change)
                prices.append(price)

            self._mock_prices[asset_code] = prices

        prices = self._mock_prices[asset_code]
        return prices[-days_back:] if len(prices) > days_back else prices


class FailoverPriceAdapter(PriceDataSource):
    """
    Failover price adapter with multiple data sources.

    Tries primary source first, falls back to secondary sources on failure.
    """

    def __init__(
        self,
        primary_adapter: Optional[PriceDataSource] = None,
        secondary_adapters: Optional[List[PriceDataSource]] = None,
        mock_adapter: Optional[PriceDataSource] = None,
    ):
        self.primary_adapter = primary_adapter or TusharePriceAdapter()
        self.secondary_adapters = secondary_adapters or [AksharePriceAdapter()]
        self.mock_adapter = mock_adapter or MockPriceAdapter()

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int
    ) -> Optional[List[float]]:
        """Get prices with failover"""
        # Try primary adapter
        prices = self.primary_adapter.get_prices(asset_code, end_date, days_back)
        if prices:
            return prices

        # Try secondary adapters
        for adapter in self.secondary_adapters:
            prices = adapter.get_prices(asset_code, end_date, days_back)
            if prices:
                logger.info(f"Using secondary data source for {asset_code}")
                return prices

        # Fall back to mock adapter for development
        logger.warning(f"Using mock data for {asset_code}")
        return self.mock_adapter.get_prices(asset_code, end_date, days_back)


class PriceDataCache:
    """Simple cache for price data to reduce API calls"""

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: Dict[str, tuple[List[float], datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(
        self,
        asset_code: str,
        end_date: date
    ) -> Optional[List[float]]:
        """Get cached prices if available and not expired"""
        cache_key = f"{asset_code}_{end_date}"

        if cache_key in self._cache:
            prices, cached_at = self._cache[cache_key]
            if timezone.now() - cached_at < self._ttl:
                return prices
            else:
                # Expired, remove from cache
                del self._cache[cache_key]

        return None

    def set(
        self,
        asset_code: str,
        end_date: date,
        prices: List[float]
    ):
        """Cache prices"""
        cache_key = f"{asset_code}_{end_date}"
        self._cache[cache_key] = (prices, timezone.now())

    def clear(self):
        """Clear all cached data"""
        self._cache.clear()


class RotationPriceDataService:
    """
    Service for fetching price data for rotation module.

    Uses failover adapter and caching.
    """

    def __init__(
        self,
        adapter: Optional[PriceDataSource] = None,
        cache: Optional[PriceDataCache] = None,
    ):
        self.adapter = adapter or FailoverPriceAdapter()
        self.cache = cache or PriceDataCache()

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int = 252
    ) -> Optional[List[float]]:
        """
        Get price data for an asset.

        Args:
            asset_code: Asset code (e.g., "510300" for ETF)
            end_date: End date for price data
            days_back: Number of days of history to fetch

        Returns:
            List of closing prices (oldest to newest) or None if unavailable
        """
        # Check cache first
        cached_prices = self.cache.get(asset_code, end_date)
        if cached_prices and len(cached_prices) >= days_back:
            return cached_prices[-days_back:]

        # Fetch from adapter
        prices = self.adapter.get_prices(asset_code, end_date, days_back)

        if prices:
            # Cache the results
            self.cache.set(asset_code, end_date, prices)

        return prices

    def get_multiple_prices(
        self,
        asset_codes: List[str],
        end_date: date,
        days_back: int = 252
    ) -> Dict[str, List[float]]:
        """
        Get price data for multiple assets.

        Args:
            asset_codes: List of asset codes
            end_date: End date for price data
            days_back: Number of days of history to fetch

        Returns:
            Dictionary mapping asset codes to price lists
        """
        result = {}

        for asset_code in asset_codes:
            prices = self.get_prices(asset_code, end_date, days_back)
            if prices:
                result[asset_code] = prices

        return result

    def clear_cache(self):
        """Clear the price cache"""
        self.cache.clear()
