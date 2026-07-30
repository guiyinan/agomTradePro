"""Typed market-price boundaries shared by Account application consumers."""

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, TypedDict

PriceFreshness = Literal["historical", "realtime", "close_fallback"]


@dataclass(frozen=True)
class MarketPriceResult:
    """Validated provider result independent of infrastructure implementations."""

    normalized_code: str
    price: float
    as_of: date | None
    source: str
    freshness: PriceFreshness
    is_fallback: bool = False
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject invalid prices and unauditable provenance at the boundary."""

        if not isinstance(self.normalized_code, str) or not self.normalized_code.strip():
            raise ValueError("价格结果缺少资产代码")
        if (
            isinstance(self.price, bool)
            or not isinstance(self.price, (int, float))
            or not math.isfinite(self.price)
            or self.price <= 0
        ):
            raise ValueError("价格结果必须为正有限数")
        if self.as_of is not None and (
            not isinstance(self.as_of, date) or isinstance(self.as_of, datetime)
        ):
            raise ValueError("价格结果日期无效")
        if (
            not isinstance(self.source, str)
            or not self.source.strip()
            or len(self.source) > 128
            or any(character in "\r\n" for character in self.source)
        ):
            raise ValueError("价格结果缺少数据来源")
        if not isinstance(self.freshness, str) or self.freshness not in {
            "historical",
            "realtime",
            "close_fallback",
        }:
            raise ValueError("价格结果新鲜度类型无效")
        if not isinstance(self.is_fallback, bool):
            raise ValueError("价格结果 fallback 标记无效")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("价格结果观测时间必须包含时区")
        if self.freshness == "realtime" and self.observed_at is None:
            raise ValueError("实时价格结果必须包含源观测时间")


class MarketPriceMetadata(TypedDict):
    """Auditable price metadata exposed to Account use cases."""

    price: Decimal
    asset_code: str
    source: str
    timestamp: datetime | None
    observed_at: datetime | None
    trade_date: date | None
    requested_trade_date: date | None
    freshness: str
    is_fallback: bool


class MarketPriceProvider(Protocol):
    """Canonical provider capability required by Account infrastructure."""

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceResult | None:
        """Return a validated canonical price result when available."""

        ...

    def clear_cache(self) -> None:
        """Clear provider-owned price caches when supported."""

        ...


class MarketPriceServiceProtocol(Protocol):
    """Price lookup boundary required by Account position use cases."""

    def get_price_with_metadata(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceMetadata | None:
        """Return a positive price with canonical provenance metadata."""

        ...


__all__ = [
    "MarketPriceMetadata",
    "MarketPriceProvider",
    "MarketPriceResult",
    "MarketPriceServiceProtocol",
    "PriceFreshness",
]
