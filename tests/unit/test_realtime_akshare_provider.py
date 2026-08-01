from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from apps.realtime.domain.entities import AssetType, RealtimePrice
from apps.realtime.infrastructure.repositories import (
    AKSharePriceDataProvider,
    CompositePriceDataProvider,
)


class _StubAK:
    def fund_etf_spot_em(self):
        return pd.DataFrame(
            {
                "代码": ["510300"],
                "名称": ["沪深300ETF"],
                "最新价": [3.91],
                "涨跌额": [0.02],
                "涨跌幅": [0.51],
                "成交量": [123456],
                "更新时间": [datetime(2026, 7, 31, 7, 0, tzinfo=UTC)],
            }
        )

    def stock_zh_a_spot_em(self):
        return pd.DataFrame(
            {
                "代码": ["000001"],
                "名称": ["平安银行"],
                "最新价": [12.34],
                "涨跌额": [0.11],
                "涨跌幅": [0.90],
                "成交量": [654321],
                "更新时间": [datetime(2026, 7, 31, 7, 0, tzinfo=UTC)],
            }
        )


def test_akshare_price_provider_reads_live_etf_snapshot(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_akshare_module",
        return_value=_StubAK(),
    )
    provider = AKSharePriceDataProvider()
    mocker.patch.object(provider._quote_repo, "get_latest", return_value=None)
    mocker.patch.object(provider._price_repo, "get_latest", return_value=None)
    bulk_upsert = mocker.patch.object(provider._quote_repo, "bulk_upsert")

    price = provider.get_realtime_price("510300.SH")

    assert price is not None
    assert price.asset_type == AssetType.FUND
    assert price.price == Decimal("3.91")
    assert price.source == "akshare"
    bulk_upsert.assert_not_called()
    assert price.timestamp == datetime(2026, 7, 31, 7, 0, tzinfo=UTC)


def test_akshare_price_provider_batch_reads_stock_and_etf_snapshots(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_akshare_module",
        return_value=_StubAK(),
    )
    provider = AKSharePriceDataProvider()
    mocker.patch.object(provider._quote_repo, "get_latest", return_value=None)
    mocker.patch.object(provider._price_repo, "get_latest", return_value=None)
    bulk_upsert = mocker.patch.object(provider._quote_repo, "bulk_upsert")

    prices = provider.get_realtime_prices_batch(["510300.SH", "000001.SZ"])

    assert len(prices) == 2
    assert {price.asset_code for price in prices} == {"510300.SH", "000001.SZ"}
    bulk_upsert.assert_not_called()


def test_akshare_price_provider_falls_back_to_direct_quote_for_single_asset(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_akshare_module",
        return_value=_StubAK(),
    )
    provider = AKSharePriceDataProvider()
    mocker.patch.object(provider._quote_repo, "get_latest", return_value=None)
    mocker.patch.object(provider._price_repo, "get_latest", return_value=None)
    mocker.patch.object(provider, "_load_spot_frame", return_value=pd.DataFrame())
    bulk_upsert = mocker.patch.object(provider._quote_repo, "bulk_upsert")
    snapshot = mocker.Mock(
        stock_code="510300.SH",
        price=Decimal("4.01"),
        change=Decimal("0.03"),
        change_pct=0.75,
        volume=987654,
        source="eastmoney",
        open=None,
        high=None,
        low=None,
        pre_close=None,
        amount=None,
        bid=None,
        ask=None,
        observed_at=datetime(2026, 7, 31, 7, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 31, 7, 0, 2, tzinfo=UTC),
    )
    gateway = mocker.Mock()
    gateway.get_quote_snapshots.return_value = [snapshot]
    mocker.patch.object(provider, "_get_eastmoney_gateway", return_value=gateway)

    price = provider.get_realtime_price("510300.SH")

    assert price is not None
    assert price.asset_code == "510300.SH"
    assert price.price == Decimal("4.01")
    assert price.source == "eastmoney"
    bulk_upsert.assert_not_called()
    assert price.timestamp == datetime(2026, 7, 31, 7, 0, tzinfo=UTC)


def test_akshare_price_provider_batch_falls_back_to_direct_quotes(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_akshare_module",
        return_value=_StubAK(),
    )
    provider = AKSharePriceDataProvider()
    mocker.patch.object(provider._quote_repo, "get_latest", return_value=None)
    mocker.patch.object(provider._price_repo, "get_latest", return_value=None)
    mocker.patch.object(provider, "_load_spot_frame", return_value=pd.DataFrame())
    bulk_upsert = mocker.patch.object(provider._quote_repo, "bulk_upsert")
    snapshot = mocker.Mock(
        stock_code="399006.SZ",
        price=Decimal("2100.10"),
        change=Decimal("-5.10"),
        change_pct=-0.24,
        volume=500,
        source="eastmoney",
        open=None,
        high=None,
        low=None,
        pre_close=None,
        amount=None,
        bid=None,
        ask=None,
        observed_at=datetime(2026, 7, 31, 7, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 31, 7, 0, 2, tzinfo=UTC),
    )
    gateway = mocker.Mock()
    gateway.get_quote_snapshots.return_value = [snapshot]
    mocker.patch.object(provider, "_get_eastmoney_gateway", return_value=gateway)

    prices = provider.get_realtime_prices_batch(["399006.SZ"])

    assert len(prices) == 1
    assert prices[0].asset_code == "399006.SZ"
    assert prices[0].price == Decimal("2100.10")
    bulk_upsert.assert_not_called()


def test_akshare_batch_avoids_repeating_remote_loads_after_fallback_exhausted(
    mocker, caplog
) -> None:
    provider = AKSharePriceDataProvider()
    mocker.patch.object(provider._quote_repo, "get_latest", return_value=None)
    mocker.patch.object(provider._price_repo, "get_latest", return_value=None)
    load_spot_frame = mocker.patch.object(provider, "_load_spot_frame", return_value=pd.DataFrame())
    mocker.patch.object(provider, "_load_direct_quotes", return_value={})

    caplog.set_level("WARNING")
    prices = provider.get_realtime_prices_batch(["510300.SH", "000001.SZ"])

    assert prices == []
    assert load_spot_frame.call_count == 2
    assert "AKShare batch fallback exhausted" in caplog.text


def test_composite_price_provider_merges_partial_batch_results() -> None:
    class _StubProvider:
        def __init__(self, prices):
            self._prices = prices

        def get_realtime_price(self, asset_code):
            return None

        def get_realtime_prices_batch(self, asset_codes):
            return [price for price in self._prices if price.asset_code in asset_codes]

        def is_available(self):
            return True

    provider = CompositePriceDataProvider(
        [
            _StubProvider(
                [
                    RealtimePrice(
                        asset_code="510300.SH",
                        asset_type=AssetType.FUND,
                        price=Decimal("4.01"),
                        change=None,
                        change_pct=None,
                        volume=100,
                        timestamp=datetime.now(UTC),
                        source="eastmoney",
                    )
                ]
            ),
            _StubProvider(
                [
                    RealtimePrice(
                        asset_code="000001.SZ",
                        asset_type=AssetType.EQUITY,
                        price=Decimal("12.34"),
                        change=None,
                        change_pct=None,
                        volume=200,
                        timestamp=datetime.now(UTC),
                        source="eastmoney",
                    )
                ]
            ),
        ]
    )

    prices = provider.get_realtime_prices_batch(["510300.SH", "000001.SZ"])

    assert [price.asset_code for price in prices] == ["510300.SH", "000001.SZ"]


def test_composite_price_provider_skips_stale_result_and_uses_next_provider() -> None:
    """A persisted stale quote must not prevent the live failover provider from running."""

    reference_time = datetime.now(UTC)

    class _StubProvider:
        def __init__(self, price: RealtimePrice) -> None:
            self.price = price
            self.calls: list[list[str]] = []

        def get_realtime_price(self, asset_code: str) -> RealtimePrice:
            return self.price

        def get_realtime_prices_batch(
            self,
            asset_codes: list[str],
        ) -> list[RealtimePrice]:
            self.calls.append(asset_codes)
            return [self.price]

        def is_available(self) -> bool:
            return True

    stale_provider = _StubProvider(
        RealtimePrice(
            asset_code="000001.SH",
            asset_type=AssetType.INDEX,
            price=Decimal("3880.10"),
            change=None,
            change_pct=None,
            volume=100,
            timestamp=reference_time - timedelta(days=100),
            source="data_center",
        )
    )
    live_price = RealtimePrice(
        asset_code="000001.SH",
        asset_type=AssetType.INDEX,
        price=Decimal("3804.69"),
        change=None,
        change_pct=None,
        volume=200,
        timestamp=reference_time,
        source="tencent",
    )
    live_provider = _StubProvider(live_price)
    provider = CompositePriceDataProvider(
        [stale_provider, live_provider],
        max_price_age_seconds=300,
    )

    prices = provider.get_realtime_prices_batch(["000001.SH"])

    assert prices == [live_price]
    assert stale_provider.calls == [["000001.SH"]]
    assert live_provider.calls == [["000001.SH"]]
