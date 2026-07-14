"""Orchestration contracts for polling, alert claiming, and notification."""

from datetime import UTC, datetime
from decimal import Decimal

from apps.realtime.application.price_polling_service import PricePollingService
from apps.realtime.domain.entities import (
    AlertCondition,
    AlertStatus,
    AssetType,
    PriceAlert,
    RealtimePrice,
)


def _price(value: str) -> RealtimePrice:
    return RealtimePrice(
        asset_code="510300.SH",
        asset_type=AssetType.FUND,
        price=Decimal(value),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=datetime.now(UTC),
        source="test",
    )


class FakePriceRepository:
    def __init__(self, old_price: RealtimePrice | None, events: list[str]) -> None:
        self.current = old_price
        self.events = events

    def get_latest_prices(self, asset_codes: list[str]) -> list[RealtimePrice]:
        self.events.append("read-old")
        return [self.current] if self.current is not None else []

    def save_prices_batch(self, prices: list[RealtimePrice]) -> None:
        self.events.append("save-prices")
        self.current = prices[0]

    def get_latest_price(self, asset_code: str) -> RealtimePrice | None:
        return self.current

    def save_price(self, price: RealtimePrice) -> None:
        self.current = price


class FakeProvider:
    def __init__(self, price: RealtimePrice, events: list[str]) -> None:
        self.price = price
        self.events = events

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        self.events.append("fetch")
        return [self.price]

    def get_realtime_price(self, asset_code: str) -> RealtimePrice:
        return self.price

    def is_available(self) -> bool:
        return True


class FakeWatchlist:
    def get_all_monitored_assets(self) -> list[str]:
        return ["510300.SH"]


class FakePositions:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def update_position_prices(self, prices: dict[str, Decimal]) -> list[dict]:
        self.events.append("update-positions")
        return []


class FakeSubscriptions:
    def list_active_asset_codes(self) -> list[str]:
        return ["510300.SH"]


class FakeAlerts:
    def __init__(self, alert: PriceAlert, events: list[str]) -> None:
        self.alert = alert
        self.events = events

    def list_active_for_assets(self, asset_codes: list[str]) -> list[PriceAlert]:
        self.events.append("list-alerts")
        return [self.alert] if self.alert.status is AlertStatus.ACTIVE else []

    def claim_trigger(
        self,
        alert_id: int,
        trigger_price: Decimal,
        triggered_at: datetime,
    ) -> PriceAlert | None:
        self.events.append("claim-alert")
        if self.alert.status is not AlertStatus.ACTIVE:
            return None
        self.alert = PriceAlert(
            **{
                **self.alert.__dict__,
                "status": AlertStatus.TRIGGERED,
                "triggered_price": trigger_price,
                "triggered_at": triggered_at,
            }
        )
        return self.alert


class FakeNotifier:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def publish_price(self, price: RealtimePrice) -> None:
        self.events.append("publish-price")
        if self.fail:
            raise RuntimeError("channel unavailable")

    def publish_alert(self, alert: PriceAlert) -> None:
        self.events.append("publish-alert")
        if self.fail:
            raise RuntimeError("channel unavailable")

    def subscriptions_changed(self, owner_id: int) -> None:
        return None


def _service(events: list[str], *, notifier_fail: bool = False):
    alert = PriceAlert(
        id=17,
        owner_id=9,
        asset_code="510300.SH",
        condition=AlertCondition.CROSS_UP,
        threshold=Decimal("3.5"),
    )
    alerts = FakeAlerts(alert, events)
    service = PricePollingService(
        price_repository=FakePriceRepository(_price("3.4"), events),
        price_provider=FakeProvider(_price("3.6"), events),
        watchlist_provider=FakeWatchlist(),
        position_repository=FakePositions(events),
        subscription_repository=FakeSubscriptions(),
        alert_repository=alerts,
        notifier=FakeNotifier(events, fail=notifier_fail),
    )
    return service, alerts


def test_polling_persists_before_claim_and_claims_before_notify() -> None:
    events: list[str] = []
    service, alerts = _service(events)

    snapshot = service.poll_and_update_prices()

    assert snapshot.success_count == 1
    assert events.index("read-old") < events.index("fetch")
    assert events.index("save-prices") < events.index("claim-alert")
    assert events.index("claim-alert") < events.index("publish-alert")
    assert alerts.alert.status is AlertStatus.TRIGGERED
    assert alerts.alert.triggered_price == Decimal("3.6")


def test_one_crossing_emits_one_alert_across_repeated_polls() -> None:
    events: list[str] = []
    service, _ = _service(events)

    service.poll_and_update_prices()
    service.poll_and_update_prices()

    assert events.count("publish-alert") == 1
    assert events.count("publish-price") == 2


def test_broadcast_failure_preserves_price_and_trigger_claim() -> None:
    events: list[str] = []
    service, alerts = _service(events, notifier_fail=True)

    snapshot = service.poll_and_update_prices()

    assert snapshot.success_count == 1
    assert service.price_repository.current.price == Decimal("3.6")
    assert alerts.alert.status is AlertStatus.TRIGGERED
