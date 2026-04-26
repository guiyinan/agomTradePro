"""Legacy market data provider kept in infrastructure for compatibility."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

logger = logging.getLogger(__name__)


class LegacyPriceProvider:
    """
    Historical market data provider backed by concrete equity/fund adapters.

    This compatibility path remains in infrastructure because it composes
    adapter implementations directly.
    """

    def __init__(self, cache_ttl_minutes: int = 30):
        self._stock_adapter = None
        self._fund_adapter = None
        self.cache_ttl_minutes = cache_ttl_minutes
        self._price_cache: dict[str, tuple[float, datetime]] = {}

    @property
    def stock_adapter(self):
        if self._stock_adapter is None:
            from apps.equity.infrastructure.adapters import TushareStockAdapter

            self._stock_adapter = TushareStockAdapter()
        return self._stock_adapter

    @property
    def fund_adapter(self):
        if self._fund_adapter is None:
            from apps.fund.infrastructure.adapters.tushare_fund_adapter import (
                TushareFundAdapter,
            )

            self._fund_adapter = TushareFundAdapter()
        return self._fund_adapter

    def get_price(self, asset_code: str, trade_date: date | None = None) -> float | None:
        cached_price, cached_time = self._price_cache.get(asset_code, (None, None))
        if cached_price is not None and cached_time is not None:
            if datetime.now(UTC) - cached_time < timedelta(minutes=self.cache_ttl_minutes):
                logger.debug("cache hit for %s = %s", asset_code, cached_price)
                return cached_price

        if asset_code.endswith((".SZ", ".SH", ".BJ")):
            price = self._get_stock_price(asset_code, trade_date)
        elif asset_code.endswith((".OF", ".OFC")):
            price = self._get_fund_price(asset_code, trade_date)
        else:
            logger.warning("unknown asset type for %s; fallback to stock adapter", asset_code)
            price = self._get_stock_price(asset_code, trade_date)

        if price is not None:
            self._price_cache[asset_code] = (price, datetime.now(UTC))

        return price

    def _get_stock_price(self, stock_code: str, trade_date: date | None = None) -> float | None:
        try:
            if trade_date is None:
                trade_date = date.today()
                end_date = trade_date.strftime("%Y%m%d")
                start_date = (trade_date - timedelta(days=7)).strftime("%Y%m%d")
            else:
                start_date = trade_date.strftime("%Y%m%d")
                end_date = trade_date.strftime("%Y%m%d")

            df = self.stock_adapter.fetch_daily_data(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df.empty:
                logger.warning("no stock data for %s @ %s", stock_code, trade_date)
                return None

            latest = df.iloc[-1]
            price = float(latest["close"])
            logger.debug(
                "stock price %s = %s @ %s",
                stock_code,
                price,
                latest["trade_date"].date(),
            )
            return price
        except Exception as exc:
            logger.error("failed to fetch stock price for %s: %s", stock_code, exc)
            return None

    def _get_fund_price(self, fund_code: str, trade_date: date | None = None) -> float | None:
        try:
            if trade_date is None:
                trade_date = date.today()
                end_date = trade_date.strftime("%Y%m%d")
                start_date = (trade_date - timedelta(days=7)).strftime("%Y%m%d")
            else:
                start_date = trade_date.strftime("%Y%m%d")
                end_date = trade_date.strftime("%Y%m%d")

            df = self.fund_adapter.fetch_fund_daily(
                fund_code=fund_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df.empty:
                logger.warning("no fund nav for %s @ %s", fund_code, trade_date)
                return None

            latest = df.iloc[-1]
            nav = float(latest["unit_nav"])
            logger.debug("fund nav %s = %s @ %s", fund_code, nav, latest["end_date"])
            return nav
        except Exception as exc:
            logger.error("failed to fetch fund nav for %s: %s", fund_code, exc)
            return None

    def get_latest_price(self, asset_code: str) -> float | None:
        return self.get_price(asset_code, trade_date=None)

    def clear_cache(self) -> None:
        self._price_cache.clear()
        logger.info("price cache cleared")

    def get_batch_prices(
        self,
        asset_codes: list[str],
        trade_date: date | None = None,
    ) -> dict[str, float | None]:
        return {code: self.get_price(code, trade_date) for code in asset_codes}
