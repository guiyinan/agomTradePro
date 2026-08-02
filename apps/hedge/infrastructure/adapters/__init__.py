"""Validated persisted-price and last-known-good adapters for hedge analytics."""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import date, datetime, timedelta
from typing import Protocol, TypedDict

from django.core.cache import cache

from apps.data_center.application.public import get_price_bar_repository_port
from apps.data_center.domain.protocols import PriceBarRepositoryProtocol

logger = logging.getLogger(__name__)

HEDGE_PRICE_CACHE_PREFIX = "hedge:prices:v2"
HEDGE_PRICE_CACHE_TIMEOUT = 86400


class HedgeDataSource(Protocol):
    """Historical price-series contract consumed by hedge calculations."""

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60,
        *,
        cache_result: bool = True,
    ) -> list[float] | None:
        """Return real historical closes in ascending date order when available."""


class _CachedPricePayload(TypedDict):
    asset_code: str
    end_date: str
    days: int
    prices: list[float]


def _validate_request(asset_code: object, end_date: object, days: object) -> tuple[str, date, int]:
    """Validate the persistence/cache request boundary before any I/O."""

    if not isinstance(asset_code, str) or not asset_code.strip():
        raise ValueError("asset_code must be a non-empty string")
    if not isinstance(end_date, date) or isinstance(end_date, datetime):
        raise ValueError("end_date must be a date")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 1:
        raise ValueError("days must be an integer greater than one")
    return asset_code.strip().upper(), end_date, days


def _normalize_prices(value: object, *, days: int) -> list[float] | None:
    """Narrow an external/cache value to finite positive historical closes."""

    if not isinstance(value, (list, tuple)) or not value or len(value) > days:
        return None
    prices: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        price = float(item)
        if not math.isfinite(price) or price <= 0:
            return None
        prices.append(price)
    return prices


def _cache_key(asset_code: str, end_date: date, days: int) -> str:
    """Build a backend-safe key scoped to the exact historical request."""

    scope = f"{asset_code}|{end_date.isoformat()}|{days}"
    digest = hashlib.blake2s(scope.encode("utf-8"), digest_size=12).hexdigest()
    return f"{HEDGE_PRICE_CACHE_PREFIX}:{digest}"


def _cache_hedge_prices(
    asset_code: str,
    end_date: date,
    days: int,
    prices: list[float],
) -> None:
    """Store and verify one exact-scope last-known-good historical series."""

    normalized_code, normalized_date, normalized_days = _validate_request(
        asset_code, end_date, days
    )
    normalized_prices = _normalize_prices(prices, days=normalized_days)
    if normalized_prices is None:
        raise ValueError("prices must contain finite positive historical closes")
    key = _cache_key(normalized_code, normalized_date, normalized_days)
    payload: _CachedPricePayload = {
        "asset_code": normalized_code,
        "end_date": normalized_date.isoformat(),
        "days": normalized_days,
        "prices": normalized_prices,
    }
    try:
        cache.set(key, payload, timeout=HEDGE_PRICE_CACHE_TIMEOUT)
        verified = _parse_cached_payload(
            cache.get(key),
            asset_code=normalized_code,
            end_date=normalized_date,
            days=normalized_days,
        )
        if verified != normalized_prices:
            cache.delete(key)
            logger.warning("Hedge historical price cache verification failed")
    except Exception as exc:
        logger.warning(
            "Hedge historical price cache write failed: error_type=%s",
            type(exc).__name__,
        )


def _parse_cached_payload(
    value: object,
    *,
    asset_code: str,
    end_date: date,
    days: int,
) -> list[float] | None:
    """Validate cache metadata and series before hedge analytics consume it."""

    if not isinstance(value, dict):
        return None
    if (
        value.get("asset_code") != asset_code
        or value.get("end_date") != end_date.isoformat()
        or value.get("days") != days
    ):
        return None
    return _normalize_prices(value.get("prices"), days=days)


def _get_cached_hedge_prices(
    asset_code: str,
    end_date: date,
    days: int,
) -> list[float] | None:
    """Return only an exact-scope, validated last-known-good historical series."""

    normalized_code, normalized_date, normalized_days = _validate_request(
        asset_code, end_date, days
    )
    key = _cache_key(normalized_code, normalized_date, normalized_days)
    try:
        return _parse_cached_payload(
            cache.get(key),
            asset_code=normalized_code,
            end_date=normalized_date,
            days=normalized_days,
        )
    except Exception as exc:
        logger.warning(
            "Hedge historical price cache read failed: error_type=%s",
            type(exc).__name__,
        )
        return None


class _PersistedPriceAdapter:
    """Base adapter for governed Data Center price bars."""

    def __init__(self, repository: PriceBarRepositoryProtocol | None = None) -> None:
        self._repo = repository if repository is not None else get_price_bar_repository_port()

    def _load_prices(self, asset_code: str, end_date: date, days: int) -> list[float] | None:
        normalized_code, normalized_date, normalized_days = _validate_request(
            asset_code, end_date, days
        )
        start_date = normalized_date - timedelta(days=normalized_days * 2)
        bars = self._repo.get_bars(
            normalized_code,
            start=start_date,
            end=normalized_date,
            limit=normalized_days * 4,
        )
        prices = [float(bar.close) for bar in reversed(bars)]
        return _normalize_prices(prices[-normalized_days:], days=normalized_days)


class TushareHedgeAdapter(_PersistedPriceAdapter):
    """Read governed price bars using a Tushare-style canonical asset code."""

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60,
        *,
        cache_result: bool = True,
    ) -> list[float] | None:
        """Return persisted historical closes without fabricating missing periods."""

        del cache_result
        return self._load_prices(self._convert_to_ts_code(asset_code), end_date, days)

    @staticmethod
    def _convert_to_ts_code(asset_code: str) -> str:
        """Convert a bare mainland security code to its exchange suffix."""

        normalized = asset_code.strip().upper()
        if "." in normalized:
            return normalized
        if normalized.startswith(("5", "6")):
            return f"{normalized}.SH"
        if normalized.startswith(("0", "1", "3")):
            return f"{normalized}.SZ"
        return normalized


class AkshareHedgeAdapter(_PersistedPriceAdapter):
    """Read governed price bars using the supplied Data Center asset code."""

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60,
        *,
        cache_result: bool = True,
    ) -> list[float] | None:
        """Return persisted historical closes without fabricating missing periods."""

        del cache_result
        return self._load_prices(asset_code, end_date, days)


class CachedHedgeAdapter:
    """Read an exact-scope last-known-good historical series from cache."""

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60,
        *,
        cache_result: bool = True,
    ) -> list[float] | None:
        """Return validated history; a single realtime quote is never expanded."""

        del cache_result
        return _get_cached_hedge_prices(asset_code, end_date, days)


class FailoverHedgeAdapter:
    """Try governed persisted readers, then exact-scope cached history."""

    def __init__(self, sources: list[HedgeDataSource] | None = None) -> None:
        self.sources: list[HedgeDataSource] = (
            list(sources)
            if sources is not None
            else [TushareHedgeAdapter(), AkshareHedgeAdapter(), CachedHedgeAdapter()]
        )

    def get_asset_prices(
        self,
        asset_code: str,
        end_date: date,
        days: int = 60,
        *,
        cache_result: bool = True,
    ) -> list[float] | None:
        """Return the first validated real historical series, with safe caching."""

        normalized_code, normalized_date, normalized_days = _validate_request(
            asset_code, end_date, days
        )
        last_error_type: str | None = None
        for index, source in enumerate(self.sources):
            try:
                candidate = source.get_asset_prices(
                    normalized_code,
                    normalized_date,
                    normalized_days,
                )
                prices = _normalize_prices(candidate, days=normalized_days)
                if prices is None:
                    continue
                if index > 0:
                    logger.info("Using hedge historical price fallback source %s", index + 1)
                if cache_result and not isinstance(source, CachedHedgeAdapter):
                    _cache_hedge_prices(
                        normalized_code,
                        normalized_date,
                        normalized_days,
                        prices,
                    )
                return prices
            except Exception as exc:
                last_error_type = type(exc).__name__
                logger.warning(
                    "Hedge historical price source failed: source=%s error_type=%s",
                    index + 1,
                    last_error_type,
                )
        if last_error_type is not None:
            logger.warning(
                "All hedge historical price sources failed: error_type=%s",
                last_error_type,
            )
        return None


_hedge_adapter_instance: HedgeDataSource | None = None


def get_hedge_adapter() -> HedgeDataSource:
    """Return the process-local hedge price adapter singleton."""

    global _hedge_adapter_instance
    if _hedge_adapter_instance is None:
        _hedge_adapter_instance = FailoverHedgeAdapter()
    return _hedge_adapter_instance
