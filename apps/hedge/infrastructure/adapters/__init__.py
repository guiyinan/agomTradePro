"""
Hedge Module Infrastructure Layer - Data Adapters

Data source adapters with failover support for hedge portfolio management.
Follows the failover pattern: Primary (Tushare) → Secondary (Mock/Cache)
"""

from datetime import date, timedelta
from typing import List, Optional
import logging

from shared.config.secrets import get_secrets

logger = logging.getLogger(__name__)


class HedgeDataSource:
    """Protocol for hedge data sources"""

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """
        Get historical prices for an asset.

        Args:
            asset_code: Asset code (ETF code like '510300')
            end_date: End date for price data
            days: Number of days of history to fetch

        Returns:
            List of closing prices (oldest to newest) or None if unavailable
        """
        raise NotImplementedError


class TushareHedgeAdapter(HedgeDataSource):
    """
    Tushare data source for ETF price data.

    Primary data source for hedge module.
    """

    def __init__(self):
        self._ts_pro = None
        self._initialized = False

    def _init_tushare(self):
        """Initialize Tushare connection"""
        if self._initialized:
            return

        try:
            import tushare as ts
            secrets = get_secrets()
            token = secrets.data_sources.tushare_token
            self._ts_pro = ts.pro_api(token)
            self._initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize Tushare: {e}")
            self._initialized = False

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """Get ETF prices from Tushare"""
        self._init_tushare()

        if not self._initialized or self._ts_pro is None:
            return None

        try:
            # Convert asset_code to Tushare format
            # e.g., '510300' -> '510300.SH'
            ts_code = self._convert_to_ts_code(asset_code)

            # Calculate start date
            start_date = end_date - timedelta(days=days * 2)  # Buffer for weekends

            # Fetch data
            df = self._ts_pro.fund_daily(
                ts_code=ts_code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )

            if df is None or df.empty:
                return None

            # Get closing prices (most recent last)
            prices = df['close'].tolist()

            # Return last N prices
            return prices[-days:] if len(prices) >= days else prices

        except Exception as e:
            logger.warning(f"Tushare price fetch failed for {asset_code}: {e}")
            return None

    def _convert_to_ts_code(self, asset_code: str) -> str:
        """Convert asset code to Tushare format"""
        # If already has suffix, return as-is
        if '.' in asset_code:
            return asset_code

        # Add appropriate suffix based on code
        if asset_code.startswith('5') or asset_code.startswith('6'):
            return f"{asset_code}.SH"  # Shanghai
        elif asset_code.startswith('0') or asset_code.startswith('1') or asset_code.startswith('3'):
            return f"{asset_code}.SZ"  # Shenzhen
        else:
            return asset_code


class AkshareHedgeAdapter(HedgeDataSource):
    """
    Akshare data source for ETF price data.

    Secondary data source for hedge module.
    """

    def __init__(self):
        self._initialized = False

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """Get ETF prices from Akshare"""
        try:
            import akshare as ak

            # Convert asset_code to symbol format
            symbol = self._convert_to_symbol(asset_code)

            # Calculate start date
            start_date = end_date - timedelta(days=days * 2)

            # Fetch fund ETF data
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d'),
                adjust=""
            )

            if df is None or df.empty:
                return None

            # Get closing prices
            prices = df['收盘'].tolist()

            return prices[-days:] if len(prices) >= days else prices

        except Exception as e:
            logger.warning(f"Akshare price fetch failed for {asset_code}: {e}")
            return None

    def _convert_to_symbol(self, asset_code: str) -> str:
        """Convert asset code to Akshare symbol format"""
        # Akshare uses different format - may need mapping
        # For now, return as-is and handle in fetch
        return asset_code


HEDGE_PRICE_CACHE_PREFIX = "hedge:prices"
HEDGE_PRICE_CACHE_TIMEOUT = 86400  # 24 hours


def _cache_hedge_prices(asset_code: str, prices: List[float]) -> None:
    """Cache successfully fetched prices for fallback use"""
    try:
        from django.core.cache import cache
        cache_key = f"{HEDGE_PRICE_CACHE_PREFIX}:{asset_code}"
        cache.set(cache_key, prices, timeout=HEDGE_PRICE_CACHE_TIMEOUT)
    except Exception as e:
        logger.debug(f"Failed to cache hedge prices for {asset_code}: {e}")


def _get_cached_hedge_prices(asset_code: str) -> Optional[List[float]]:
    """Retrieve cached prices from a previous successful fetch"""
    try:
        from django.core.cache import cache
        cache_key = f"{HEDGE_PRICE_CACHE_PREFIX}:{asset_code}"
        return cache.get(cache_key)
    except Exception as e:
        logger.debug(f"Failed to read cached hedge prices for {asset_code}: {e}")
        return None


class CachedHedgeAdapter(HedgeDataSource):
    """
    Cached data source for hedge module.

    Reads last-known-good prices from Django cache (written by Tushare/Akshare
    on successful fetches). Falls back to realtime price cache if no historical
    data is available.
    """

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """Return cached prices from previous successful fetches"""
        # 1. Try Django cache (last-known-good from Tushare/Akshare)
        cached = _get_cached_hedge_prices(asset_code)
        if cached and len(cached) > 0:
            logger.info(f"Returning cached prices for {asset_code} ({len(cached)} data points)")
            return cached[-days:] if len(cached) >= days else cached

        # 2. Try realtime price cache (single latest price)
        latest_price = self._get_realtime_price(asset_code)
        if latest_price is not None:
            logger.info(f"Using realtime price for {asset_code}: {latest_price}")
            return [latest_price] * days

        return None

    @staticmethod
    def _get_realtime_price(asset_code: str) -> Optional[float]:
        """Try to get latest price from realtime cache"""
        try:
            from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository
            repo = RedisRealtimePriceRepository()
            price_data = repo.get_latest_price(asset_code)
            if price_data and price_data.price > 0:
                return float(price_data.price)
        except Exception:
            pass
        return None


class FailoverHedgeAdapter(HedgeDataSource):
    """
    Failover adapter for hedge data sources.

    Tries sources in order: Tushare → Akshare → Cached
    """

    def __init__(self):
        self.sources = [
            TushareHedgeAdapter(),
            AkshareHedgeAdapter(),
            CachedHedgeAdapter(),
        ]

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """Get prices with automatic failover and caching"""
        last_error = None

        for i, source in enumerate(self.sources):
            try:
                prices = source.get_asset_prices(asset_code, end_date, days)

                if prices and len(prices) > 0:
                    if i > 0:
                        logger.info(f"Using fallback source {i+1} for {asset_code}")

                    # Cache successful results from primary sources (not CachedHedgeAdapter)
                    if not isinstance(source, CachedHedgeAdapter):
                        _cache_hedge_prices(asset_code, prices)

                    return prices

            except Exception as e:
                last_error = e
                logger.warning(f"Source {i+1} failed for {asset_code}: {e}")
                continue

        logger.error(f"All data sources failed for {asset_code}, last error: {last_error}")
        return None


# Singleton instance for use in the application
_hedge_adapter_instance = None


def get_hedge_adapter() -> HedgeDataSource:
    """Get the singleton hedge data adapter"""
    global _hedge_adapter_instance

    if _hedge_adapter_instance is None:
        _hedge_adapter_instance = FailoverHedgeAdapter()

    return _hedge_adapter_instance
