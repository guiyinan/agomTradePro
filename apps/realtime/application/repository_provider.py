"""Realtime dependency providers for application consumers."""

from __future__ import annotations

def get_realtime_price_repository():
    """Return the realtime price repository."""

    from apps.realtime.infrastructure.providers import RedisRealtimePriceRepository

    return RedisRealtimePriceRepository()


def get_realtime_price_provider():
    """Build the default chained realtime price provider."""

    from apps.realtime.infrastructure.providers import (
        AKSharePriceDataProvider,
        CompositePriceDataProvider,
        DataCenterPriceDataProvider,
        TusharePriceDataProvider,
    )

    providers = []

    try:
        providers.append(DataCenterPriceDataProvider())
    except Exception:
        pass

    providers.extend([AKSharePriceDataProvider(), TusharePriceDataProvider()])
    return CompositePriceDataProvider(providers)


def get_watchlist_provider():
    """Return the default watchlist provider."""

    from apps.realtime.infrastructure.providers import DatabaseWatchlistProvider

    return DatabaseWatchlistProvider()
