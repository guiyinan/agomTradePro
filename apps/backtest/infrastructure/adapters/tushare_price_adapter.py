"""
Legacy Tushare asset-price adapter backed by data_center facts.

The class name is preserved for existing callers, but all reads now go through
internal repositories instead of importing external SDKs directly.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from .base import (
    AssetPricePoint,
    BaseAssetPriceAdapter,
    get_asset_class_tickers,
)

logger = logging.getLogger(__name__)


def get_tushare_asset_tickers() -> dict[str, str | None]:
    """Return configured asset-class proxy tickers."""
    configured = get_asset_class_tickers()
    return {
        "a_share_growth": configured.get("a_share_growth"),
        "a_share_value": configured.get("a_share_value"),
        "china_bond": configured.get("china_bond"),
        "gold": configured.get("gold"),
        "commodity": configured.get("commodity"),
        "cash": "CASH",
    }


class TushareAssetPriceAdapter(BaseAssetPriceAdapter):
    """Compatibility adapter that reads from the unified data_center store."""

    source_name = "data_center_tushare_compat"

    def __init__(self, token: str | None = None, http_url: str | None = None):
        self._token = token
        self._http_url = http_url
        from apps.data_center.infrastructure.repositories import PriceBarRepository

        self._bars = PriceBarRepository()

    def supports(self, asset_class: str) -> bool:
        if asset_class == "cash":
            return True
        return get_tushare_asset_tickers().get(asset_class) is not None

    def get_price(self, asset_class: str, as_of_date: date) -> float | None:
        if asset_class == "cash":
            return 1.0

        ticker = get_tushare_asset_tickers().get(asset_class)
        if not ticker:
            return None
        try:
            bars = self._bars.get_bars(ticker, start=as_of_date, end=as_of_date, limit=1)
            return float(bars[0].close) if bars else None
        except Exception:
            logger.warning(
                "Failed to read asset price from data_center: %s @ %s",
                asset_class,
                as_of_date,
                exc_info=True,
            )
            return None

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        if asset_class == "cash":
            points: list[AssetPricePoint] = []
            current = start_date
            while current <= end_date:
                points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=1.0,
                        as_of_date=current,
                        source=self.source_name,
                    )
                )
                current += timedelta(days=1)
            return points

        ticker = get_tushare_asset_tickers().get(asset_class)
        if not ticker:
            return []

        try:
            history = list(
                reversed(self._bars.get_bars(ticker, start=start_date, end=end_date, limit=5000))
            )
        except Exception:
            logger.warning(
                "Failed to read asset price history from data_center: %s %s~%s",
                asset_class,
                start_date,
                end_date,
                exc_info=True,
            )
            return []

        points: list[AssetPricePoint] = []
        for item in history:
            points.append(
                AssetPricePoint(
                    asset_class=asset_class,
                    price=float(item.close),
                    as_of_date=item.bar_date,
                    source=str(item.source or self.source_name),
                )
            )
        return points
