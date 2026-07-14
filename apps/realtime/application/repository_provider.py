"""Realtime dependency providers for application consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.realtime.application.use_cases import (
        RealtimeAlertService,
        RealtimeSubscriptionService,
    )


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


def get_realtime_alert_service() -> RealtimeAlertService:
    """Compose the owner-scoped realtime alert service."""

    from apps.realtime.application.use_cases import RealtimeAlertService
    from apps.realtime.infrastructure.providers import DjangoPriceAlertRepository

    return RealtimeAlertService(DjangoPriceAlertRepository())


def get_realtime_subscription_service() -> RealtimeSubscriptionService:
    """Compose the durable subscription service."""

    from apps.realtime.application.use_cases import RealtimeSubscriptionService
    from apps.realtime.infrastructure.providers import (
        DjangoPriceSubscriptionRepository,
    )

    return RealtimeSubscriptionService(DjangoPriceSubscriptionRepository())
