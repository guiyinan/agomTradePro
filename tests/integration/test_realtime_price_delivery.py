"""End-to-end delivery from the real polling service to a WebSocket."""

from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.realtime.application.price_polling_service import PricePollingService
from apps.realtime.domain.entities import AlertCondition, AssetType, PriceAlert, RealtimePrice
from apps.realtime.infrastructure.channel_notifier import ChannelPriceNotifier
from apps.realtime.infrastructure.repositories import (
    DjangoPriceAlertRepository,
    DjangoPriceSubscriptionRepository,
)
from core.asgi import build_application

TEST_CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}


def _sync_async_test(async_test):
    @wraps(async_test)
    def wrapper(*args, **kwargs):
        return async_to_sync(async_test)(*args, **kwargs)

    return wrapper


@pytest.fixture
def delivery_identity(db):
    user = get_user_model().objects.create_user(username="delivery-owner")
    _, raw_key = UserAccessTokenModel.create_token(user=user, name="delivery")
    subscriptions = DjangoPriceSubscriptionRepository()
    subscriptions.subscribe(user.id, "510300.SH")
    alerts = DjangoPriceAlertRepository()
    alerts.create(
        PriceAlert(
            owner_id=user.id,
            asset_code="510300.SH",
            condition=AlertCondition.CROSS_UP,
            threshold=Decimal("3.5"),
        )
    )
    return user, raw_key


class MemoryPriceRepository:
    def __init__(self) -> None:
        self.current = self._price("3.4")

    @staticmethod
    def _price(value: str) -> RealtimePrice:
        return RealtimePrice(
            asset_code="510300.SH",
            asset_type=AssetType.FUND,
            price=Decimal(value),
            change=None,
            change_pct=None,
            volume=100,
            timestamp=datetime.now(UTC),
            source="delivery-test",
        )

    def get_latest_prices(self, asset_codes: list[str]) -> list[RealtimePrice]:
        return [self.current]

    def save_prices_batch(self, prices: list[RealtimePrice]) -> None:
        self.current = prices[0]

    def get_latest_price(self, asset_code: str) -> RealtimePrice:
        return self.current

    def save_price(self, price: RealtimePrice) -> None:
        self.current = price


class FixedPriceProvider:
    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        return [MemoryPriceRepository._price("3.6")]

    def get_realtime_price(self, asset_code: str) -> RealtimePrice:
        return MemoryPriceRepository._price("3.6")

    def is_available(self) -> bool:
        return True


class EmptyWatchlist:
    def get_all_monitored_assets(self) -> list[str]:
        return []


class EmptyPositions:
    def update_position_prices(self, prices: dict[str, Decimal]) -> list[dict]:
        return []


@pytest.mark.django_db(transaction=True)
@override_settings(
    REALTIME_WEBSOCKET_ENABLED=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
@_sync_async_test
async def test_real_polling_delivers_one_price_and_one_single_fire_alert(
    delivery_identity,
) -> None:
    _, raw_key = delivery_identity
    communicator = WebsocketCommunicator(
        build_application(),
        "/ws/realtime/prices/",
        headers=[
            (b"origin", b"http://testserver"),
            (b"authorization", f"Token {raw_key}".encode("ascii")),
        ],
    )
    assert (await communicator.connect())[0] is True
    ready = await communicator.receive_json_from()
    assert ready["subscriptions"] == ["510300.SH"]

    service = PricePollingService(
        price_repository=MemoryPriceRepository(),
        price_provider=FixedPriceProvider(),
        watchlist_provider=EmptyWatchlist(),
        position_repository=EmptyPositions(),
        subscription_repository=DjangoPriceSubscriptionRepository(),
        alert_repository=DjangoPriceAlertRepository(),
        notifier=ChannelPriceNotifier(),
    )
    await database_sync_to_async(service.poll_and_update_prices)()
    price_event = await communicator.receive_json_from()
    alert_event = await communicator.receive_json_from()
    assert price_event["type"] == "price.update"
    assert price_event["price"] == "3.6"
    assert alert_event["type"] == "alert.triggered"
    assert alert_event["triggered_price"] == "3.6"

    await database_sync_to_async(service.poll_and_update_prices)()
    assert (await communicator.receive_json_from())["type"] == "price.update"
    assert await communicator.receive_nothing(timeout=0.05) is True
    await communicator.disconnect()
