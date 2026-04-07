from datetime import datetime, timezone
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
    bulk_upsert.assert_called_once()


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
    bulk_upsert.assert_called_once()


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
    )
    gateway = mocker.Mock()
    gateway.get_quote_snapshots.return_value = [snapshot]
    mocker.patch.object(provider, "_get_eastmoney_gateway", return_value=gateway)

    price = provider.get_realtime_price("510300.SH")

    assert price is not None
    assert price.asset_code == "510300.SH"
    assert price.price == Decimal("4.01")
    assert price.source == "eastmoney"
    bulk_upsert.assert_called_once()


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
    )
    gateway = mocker.Mock()
    gateway.get_quote_snapshots.return_value = [snapshot]
    mocker.patch.object(provider, "_get_eastmoney_gateway", return_value=gateway)

    prices = provider.get_realtime_prices_batch(["399006.SZ"])

    assert len(prices) == 1
    assert prices[0].asset_code == "399006.SZ"
    assert prices[0].price == Decimal("2100.10")
    bulk_upsert.assert_called_once()


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
                        timestamp=datetime.now(timezone.utc),
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
                        timestamp=datetime.now(timezone.utc),
                        source="eastmoney",
                    )
                ]
            ),
        ]
    )

    prices = provider.get_realtime_prices_batch(["510300.SH", "000001.SZ"])

    assert [price.asset_code for price in prices] == ["510300.SH", "000001.SZ"]
