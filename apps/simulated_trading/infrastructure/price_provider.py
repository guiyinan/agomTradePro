"""
模拟盘价格提供器。

统一委托给 data_center 的价格服务。
"""

from datetime import date
from typing import cast

from apps.account.application.market_price_contracts import (
    MarketPriceResult,
    PriceFreshness,
)
from apps.data_center.application.price_service import PriceLookupResult, UnifiedPriceService


class DataCenterPriceProvider:
    """模拟盘内部使用的 data_center 价格提供器。"""

    def __init__(self, cache_ttl_minutes: int = 30) -> None:
        self._price_service = UnifiedPriceService()
        self.cache_ttl_minutes = cache_ttl_minutes

    def get_price(self, asset_code: str, trade_date: date | None = None) -> float | None:
        return self._price_service.get_price(asset_code=asset_code, trade_date=trade_date)

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceResult | None:
        """Return the canonical price together with its real provenance."""

        result: PriceLookupResult | None = self._price_service.get_price_result(
            asset_code=asset_code,
            trade_date=trade_date,
        )
        if result is None:
            return None
        return MarketPriceResult(
            normalized_code=result.normalized_code,
            price=result.price,
            as_of=result.as_of,
            source=result.source,
            freshness=cast(PriceFreshness, result.freshness),
            is_fallback=result.is_fallback,
            observed_at=result.observed_at,
        )

    def get_latest_price(self, asset_code: str) -> float | None:
        return self._price_service.get_latest_price(asset_code=asset_code)

    def require_price(self, asset_code: str, trade_date: date | None = None) -> float:
        return self._price_service.require_price(
            asset_code=asset_code,
            trade_date=trade_date,
        )

    def require_latest_price(self, asset_code: str) -> float:
        return self._price_service.require_latest_price(asset_code=asset_code)

    def get_batch_prices(
        self,
        asset_codes: list[str],
        trade_date: date | None = None,
    ) -> dict[str, float | None]:
        return {code: self.get_price(code, trade_date=trade_date) for code in asset_codes}

    def clear_cache(self) -> None:
        """统一价格服务当前不暴露局部缓存清理。"""
        return None
