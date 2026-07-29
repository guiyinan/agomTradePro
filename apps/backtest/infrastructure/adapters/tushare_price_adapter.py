"""
Legacy Tushare asset-price adapter backed by data_center facts.

The class name is preserved for existing callers, but all reads now go through
internal repositories instead of importing external SDKs directly.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

from django.db import DatabaseError

from .base import (
    AssetPricePoint,
    AssetPriceValidationError,
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

    def __init__(self, token: str | None = None, http_url: str | None = None) -> None:
        # Compatibility arguments are deliberately not retained: this adapter no
        # longer performs outbound requests and must not keep credentials alive.
        del token, http_url
        from apps.data_center.infrastructure.repositories import PriceBarRepository

        self._bars = PriceBarRepository()

    def supports(self, asset_class: str) -> bool:
        if asset_class == "cash":
            return True
        return get_tushare_asset_tickers().get(asset_class) is not None

    def get_price(self, asset_class: str, as_of_date: date) -> float | None:
        if type(as_of_date) is not date:
            raise ValueError("as_of_date must be a date")
        if asset_class == "cash":
            return 1.0

        ticker = get_tushare_asset_tickers().get(asset_class)
        if not ticker:
            return None
        try:
            bars = self._bars.get_bars(ticker, start=as_of_date, end=as_of_date, limit=1)
            if not bars:
                return None
            price = float(bars[0].close)
            if not math.isfinite(price) or price <= 0:
                raise AssetPriceValidationError("stored price is not positive and finite")
            return price
        except (
            ArithmeticError,
            AssetPriceValidationError,
            DatabaseError,
            LookupError,
            TypeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Failed to read asset price from data_center: %s @ %s (%s)",
                asset_class,
                as_of_date,
                type(exc).__name__,
            )
            return None

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        if type(start_date) is not date or type(end_date) is not date:
            raise ValueError("price range bounds must be dates")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if asset_class == "cash":
            cash_points: list[AssetPricePoint] = []
            current = start_date
            while current <= end_date:
                cash_points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=1.0,
                        as_of_date=current,
                        source=self.source_name,
                    )
                )
                current += timedelta(days=1)
            return cash_points

        ticker = get_tushare_asset_tickers().get(asset_class)
        if not ticker:
            return []

        try:
            history = list(
                reversed(self._bars.get_bars(ticker, start=start_date, end=end_date, limit=5000))
            )
        except (ArithmeticError, DatabaseError, LookupError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to read asset price history from data_center: %s %s~%s (%s)",
                asset_class,
                start_date,
                end_date,
                type(exc).__name__,
            )
            return []

        points: list[AssetPricePoint] = []
        for item in history:
            try:
                points.append(
                    AssetPricePoint(
                        asset_class=asset_class,
                        price=float(item.close),
                        as_of_date=item.bar_date,
                        source=str(item.source or self.source_name),
                    )
                )
            except (ArithmeticError, AssetPriceValidationError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipped invalid asset price point: %s (%s)",
                    asset_class,
                    type(exc).__name__,
                )
        return points
