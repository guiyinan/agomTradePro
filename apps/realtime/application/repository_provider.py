"""Realtime dependency providers for application consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.realtime.application.use_cases import (
        RealtimeAlertService,
        RealtimeSubscriptionService,
    )
    from apps.realtime.domain.protocols import (
        PriceAlertRepositoryProtocol,
        PriceDataProviderProtocol,
        PriceSubscriptionRepositoryProtocol,
        RealtimeChannelNotifierProtocol,
        RealtimePriceRepositoryProtocol,
        WatchlistProviderProtocol,
    )


def get_realtime_price_repository() -> RealtimePriceRepositoryProtocol:
    """Return the realtime price repository."""

    from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository

    return RedisRealtimePriceRepository()


def get_realtime_price_provider() -> PriceDataProviderProtocol:
    """Build the default chained realtime price provider."""

    from apps.realtime.infrastructure.repositories import (
        AKSharePriceDataProvider,
        CompositePriceDataProvider,
        DataCenterPriceDataProvider,
        TusharePriceDataProvider,
    )

    providers: list[PriceDataProviderProtocol] = []

    try:
        providers.append(DataCenterPriceDataProvider())
    except Exception:
        pass

    providers.extend([AKSharePriceDataProvider(), TusharePriceDataProvider()])
    return CompositePriceDataProvider(providers)


def get_watchlist_provider() -> WatchlistProviderProtocol:
    """Return the default watchlist provider."""

    from apps.realtime.infrastructure.repositories import DatabaseWatchlistProvider

    return DatabaseWatchlistProvider()


def get_realtime_alert_service() -> RealtimeAlertService:
    """Compose the owner-scoped realtime alert service."""

    from apps.realtime.application.use_cases import RealtimeAlertService
    from apps.realtime.infrastructure.repositories import DjangoPriceAlertRepository

    return RealtimeAlertService(DjangoPriceAlertRepository())


def get_realtime_subscription_service(
    *, notify_connected_clients: bool = True
) -> RealtimeSubscriptionService:
    """Compose the durable subscription service."""

    from apps.realtime.application.use_cases import RealtimeSubscriptionService
    from apps.realtime.infrastructure.channel_notifier import ChannelPriceNotifier
    from apps.realtime.infrastructure.repositories import DjangoPriceSubscriptionRepository

    notifier: RealtimeChannelNotifierProtocol | None = (
        ChannelPriceNotifier() if notify_connected_clients else None
    )
    return RealtimeSubscriptionService(DjangoPriceSubscriptionRepository(), notifier)


def get_price_alert_repository() -> PriceAlertRepositoryProtocol:
    """Return the durable price-alert repository."""

    from apps.realtime.infrastructure.repositories import DjangoPriceAlertRepository

    return DjangoPriceAlertRepository()


def get_price_subscription_repository() -> PriceSubscriptionRepositoryProtocol:
    """Return the durable price-subscription repository."""

    from apps.realtime.infrastructure.repositories import DjangoPriceSubscriptionRepository

    return DjangoPriceSubscriptionRepository()


def get_realtime_channel_notifier() -> RealtimeChannelNotifierProtocol:
    """Return the Channels-backed realtime notifier."""

    from apps.realtime.infrastructure.channel_notifier import ChannelPriceNotifier

    return ChannelPriceNotifier()
