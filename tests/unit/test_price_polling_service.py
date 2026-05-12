from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.realtime.application.price_polling_service import PricePollingService
from apps.realtime.domain.entities import AssetType, RealtimePrice
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel


class _StubPriceRepository:
    def save_prices_batch(self, prices):
        self.saved_prices = prices

    def get_latest_price(self, asset_code):
        return None


class _StubPriceProvider:
    def __init__(self, prices):
        self._prices = prices

    def get_realtime_prices_batch(self, asset_codes):
        return [price for price in self._prices if price.asset_code in asset_codes]

    def get_realtime_price(self, asset_code):
        return None


class _StubWatchlistProvider:
    def __init__(self, asset_codes):
        self._asset_codes = asset_codes

    def get_all_monitored_assets(self):
        return self._asset_codes


@pytest.mark.django_db
def test_price_polling_service_updates_position_and_account_totals() -> None:
    account = SimulatedAccountModel.objects.create(
        account_name="Price Polling Test",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("40000.00"),
        current_market_value=Decimal("60000.00"),
        total_value=Decimal("100000.00"),
    )
    position = PositionModel.objects.create(
        account=account,
        asset_code="510300.SH",
        asset_name="CSI 300 ETF",
        asset_type="fund",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("4.5000"),
        total_cost=Decimal("450.00"),
        current_price=Decimal("4.5000"),
        market_value=Decimal("450.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=datetime.now(UTC).date(),
    )

    realtime_price = RealtimePrice(
        asset_code="510300.SH",
        asset_type=AssetType.FUND,
        price=Decimal("5.0000"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=datetime.now(UTC),
        source="test",
    )
    service = PricePollingService(
        price_repository=_StubPriceRepository(),
        price_provider=_StubPriceProvider([realtime_price]),
        watchlist_provider=_StubWatchlistProvider(["510300.SH"]),
    )

    snapshot = service.poll_and_update_prices()

    position.refresh_from_db()
    account.refresh_from_db()

    assert snapshot.success_count == 1
    assert position.current_price == Decimal("5.0000")
    assert position.market_value == Decimal("500.00")
    assert position.unrealized_pnl == Decimal("50.00")
    assert position.unrealized_pnl_pct == pytest.approx(11.1111111111)
    assert account.current_market_value == Decimal("500.00")
    assert account.total_value == Decimal("40500.00")
    assert account.total_return == pytest.approx(-59.5)
