"""Validated market-price access for Account infrastructure consumers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.account.application.market_price_contracts import (
    MarketPriceMetadata,
    MarketPriceProvider,
    MarketPriceResult,
)
from apps.account.application.simulated_trading_gateway import build_market_price_provider

logger = logging.getLogger(__name__)

_CANONICAL_ASSET_CODE = re.compile(r"^[0-9]{6}\.(?:SZ|SH|BJ|OF|OFC|HK)$")
_BARE_ASSET_CODE = re.compile(r"^[0-9]{6}$")
_MAX_BATCH_SIZE = 500


@dataclass(frozen=True)
class _ValidatedPrice:
    """Canonical provider result narrowed for Account consumers."""

    result: MarketPriceResult
    price: Decimal


class MarketPriceService:
    """Return positive canonical prices with auditable Data Center provenance."""

    def __init__(self, cache_ttl_minutes: int = 30) -> None:
        """Initialize the lazy provider with a positive integer cache TTL."""

        if (
            isinstance(cache_ttl_minutes, bool)
            or not isinstance(cache_ttl_minutes, int)
            or cache_ttl_minutes <= 0
        ):
            raise ValueError("cache_ttl_minutes 必须为正整数")
        self._provider: MarketPriceProvider | None = None
        self.cache_ttl_minutes = cache_ttl_minutes

    @property
    def provider(self) -> MarketPriceProvider:
        """Build the configured price provider on first use."""

        if self._provider is None:
            self._provider = build_market_price_provider(self.cache_ttl_minutes)
        return self._provider

    def get_current_price(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> Decimal | None:
        """Return a positive finite price, or ``None`` when lookup fails."""

        normalized_code = self._normalize_asset_code(asset_code)
        self._validate_trade_date(trade_date)
        validated = self._lookup_price(normalized_code, trade_date)
        return validated.price if validated is not None else None

    def get_prices_batch(
        self,
        asset_codes: list[str],
        trade_date: date | None = None,
    ) -> dict[str, Decimal | None]:
        """Return prices keyed by each requested code while deduplicating lookups."""

        if not isinstance(asset_codes, list):
            raise ValueError("asset_codes 必须为列表")
        if len(asset_codes) > _MAX_BATCH_SIZE:
            raise ValueError(f"单次最多查询 {_MAX_BATCH_SIZE} 个资产代码")
        self._validate_trade_date(trade_date)

        normalized_by_request = {
            requested_code: self._normalize_asset_code(requested_code)
            for requested_code in asset_codes
        }
        prices_by_normalized: dict[str, Decimal | None] = {}
        for normalized_code in dict.fromkeys(normalized_by_request.values()):
            validated = self._lookup_price(normalized_code, trade_date)
            prices_by_normalized[normalized_code] = (
                validated.price if validated is not None else None
            )

        return {
            requested_code: prices_by_normalized[normalized_code]
            for requested_code, normalized_code in normalized_by_request.items()
        }

    def get_price_with_metadata(
        self,
        asset_code: str,
        trade_date: date | None = None,
    ) -> MarketPriceMetadata | None:
        """Return price metadata sourced from the canonical Data Center result."""

        normalized_code = self._normalize_asset_code(asset_code)
        self._validate_trade_date(trade_date)
        validated = self._lookup_price(normalized_code, trade_date)
        if validated is None:
            return None

        result = validated.result
        return {
            "price": validated.price,
            "asset_code": result.normalized_code,
            "source": result.source,
            "timestamp": result.observed_at,
            "observed_at": result.observed_at,
            "trade_date": result.as_of,
            "requested_trade_date": trade_date,
            "freshness": result.freshness,
            "is_fallback": result.is_fallback,
        }

    def clear_cache(self) -> None:
        """Clear an initialized provider cache without forcing initialization."""

        if self._provider is not None:
            self._provider.clear_cache()
            logger.info("市场价格服务缓存已清空")

    @staticmethod
    def _normalize_asset_code(asset_code: str) -> str:
        """Validate and normalize a supported six-digit market code."""

        if not isinstance(asset_code, str):
            raise ValueError("资产代码必须为字符串")
        normalized_code = asset_code.strip().upper()
        if not normalized_code:
            raise ValueError("资产代码不能为空")

        if _CANONICAL_ASSET_CODE.fullmatch(normalized_code):
            return normalized_code
        if not _BARE_ASSET_CODE.fullmatch(normalized_code):
            raise ValueError("资产代码格式无效")

        if normalized_code.startswith(("4", "8", "92")):
            return f"{normalized_code}.BJ"
        if normalized_code.startswith(("5", "6")):
            return f"{normalized_code}.SH"
        if normalized_code.startswith(("0", "1", "2", "3")):
            return f"{normalized_code}.SZ"
        raise ValueError("资产代码无法识别交易市场")

    @staticmethod
    def _validate_trade_date(trade_date: date | None) -> None:
        """Reject datetime and other values that are not exact calendar dates."""

        if trade_date is not None and (
            not isinstance(trade_date, date) or isinstance(trade_date, datetime)
        ):
            raise ValueError("trade_date 必须为日期")

    def _lookup_price(
        self,
        normalized_code: str,
        trade_date: date | None,
    ) -> _ValidatedPrice | None:
        """Fetch and defensively validate one canonical provider result."""

        try:
            result = self.provider.get_price_result(normalized_code, trade_date)
        except Exception as exc:
            logger.warning(
                "市场价格查询失败: asset_code=%s error_type=%s",
                normalized_code,
                type(exc).__name__,
            )
            return None

        if result is None:
            logger.warning(
                "未获取到资产价格: asset_code=%s trade_date=%s",
                normalized_code,
                trade_date.isoformat() if trade_date is not None else "latest",
            )
            return None
        if not isinstance(result, MarketPriceResult):
            logger.warning("市场价格结果类型无效: asset_code=%s", normalized_code)
            return None
        if result.normalized_code != normalized_code:
            logger.warning("市场价格结果代码越界: asset_code=%s", normalized_code)
            return None
        if trade_date is not None and result.as_of != trade_date:
            logger.warning("市场价格结果日期不匹配: asset_code=%s", normalized_code)
            return None

        try:
            price = Decimal(str(result.price))
        except (InvalidOperation, ValueError):
            logger.warning("市场价格结果数值无效: asset_code=%s", normalized_code)
            return None
        if not price.is_finite() or price <= 0:
            logger.warning("市场价格结果非正有限数: asset_code=%s", normalized_code)
            return None
        return _ValidatedPrice(result=result, price=price)

    def is_available(self) -> bool:
        """Report whether the provider can be configured without issuing a quote."""

        try:
            _ = self.provider
        except Exception as exc:
            logger.warning("市场价格服务不可用: error_type=%s", type(exc).__name__)
            return False
        return True


_price_service_instance: MarketPriceService | None = None


def get_market_price_service() -> MarketPriceService:
    """Return the process-local lazy market-price service singleton."""

    global _price_service_instance
    if _price_service_instance is None:
        _price_service_instance = MarketPriceService()
    return _price_service_instance


__all__ = ["MarketPriceService", "get_market_price_service"]
