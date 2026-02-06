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


class CachedHedgeAdapter(HedgeDataSource):
    """
    Cached/Mock data source for hedge module.

    Fallback data source when external APIs fail.
    """

    def __init__(self):
        # Mock price data for common ETFs
        self._mock_prices = {
            '510300': {'base': 4.5, 'vol': 0.02},  # 沪深300
            '510500': {'base': 7.2, 'vol': 0.025},  # 中证500
            '159915': {'base': 1.8, 'vol': 0.03},   # 创业板
            '512100': {'base': 3.2, 'vol': 0.015},  # 红利ETF
            '511260': {'base': 102.5, 'vol': 0.005}, # 10年国债
            '511880': {'base': 100.2, 'vol': 0.002}, # 银行间国债
            '159985': {'base': 7.8, 'vol': 0.025},  # 商品ETF
        }

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60
    ) -> Optional[List[float]]:
        """Generate mock price data"""
        import random

        mock_data = self._mock_prices.get(asset_code)
        if not mock_data:
            # Generate default mock data
            mock_data = {'base': 10.0, 'vol': 0.02}

        base_price = mock_data['base']
        volatility = mock_data['vol']

        # Generate price series with random walk
        prices = []
        price = base_price

        # Set seed for reproducibility based on asset_code and date
        seed = hash(asset_code + end_date.strftime('%Y%m%d')) % 10000
        random.seed(seed)

        for _ in range(days):
            change = random.gauss(0, volatility)
            price = price * (1 + change)
            prices.append(max(price, 0.01))  # Ensure positive prices

        return prices


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
        """Get prices with automatic failover"""
        last_error = None

        for i, source in enumerate(self.sources):
            try:
                prices = source.get_asset_prices(asset_code, end_date, days)

                if prices and len(prices) > 0:
                    if i > 0:
                        logger.info(f"Using fallback source {i+1} for {asset_code}")

                    return prices

            except Exception as e:
                last_error = e
                logger.warning(f"Source {i+1} failed for {asset_code}: {e}")
                continue

        logger.error(f"All data sources failed for {asset_code}, last error: {last_error}")

        # Return minimal mock data as last resort
        return [100.0] * days


# Singleton instance for use in the application
_hedge_adapter_instance = None


def get_hedge_adapter() -> HedgeDataSource:
    """Get the singleton hedge data adapter"""
    global _hedge_adapter_instance

    if _hedge_adapter_instance is None:
        _hedge_adapter_instance = FailoverHedgeAdapter()

    return _hedge_adapter_instance
