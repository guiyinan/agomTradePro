"""Bulk transport must retain source, date, unit and failover checks."""

from datetime import date

import pandas as pd
import pytest

from apps.data_center.application.model_market_data import ModelMarketDataService, ModelMarketRoute
from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource
from core.exceptions import DataFetchError

DAY = date(2026, 9, 18)
CODES = ("000006.SZ", "000007.SZ")


class Client:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": "20260918",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "vol": 100,
                    "pct_chg": 0,
                    "amount": 50,
                }
                for code in kwargs["ts_code"].split(",")
            ]
        )

    def adj_factor(self, **kwargs):
        self.calls.append(("factor", kwargs))
        return pd.DataFrame(
            [
                {"ts_code": code, "trade_date": "20260918", "adj_factor": 2}
                for code in kwargs["ts_code"].split(",")
            ]
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame([{"cal_date": "20260918"}])


def test_prepared_multi_symbol_history_reduces_requests_and_preserves_units():
    client = Client()
    source = TushareModelMarketSource(client, source="configured_vendor")
    source.prepare_stock_history(CODES, DAY, DAY)
    for code in CODES:
        rows = source.stock_history(code, DAY, DAY)
        assert len(rows) == 1
        assert rows[0].asset_code == code
        assert rows[0].trade_date == DAY
        assert rows[0].volume == 10000
        assert rows[0].amount == 50000
        assert rows[0].adjustment_factor == 2
        assert rows[0].source == "configured_vendor"
    assert len(client.calls) == 2
    assert client.calls[0][1]["ts_code"] == ",".join(CODES)


def test_preparation_is_exact_window_and_does_not_reuse_a_previous_request():
    client = Client()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(CODES, DAY, DAY)
    source.stock_history(CODES[0], date(2026, 9, 17), DAY)
    assert len(client.calls) == 4


def test_prepared_data_still_runs_cross_source_consistency_before_storage():
    client = Client()
    source = TushareModelMarketSource(client)
    stored = []
    port = ModelMarketDataService(
        (ModelMarketRoute("vendor", source, requires_reference=True),),
        enable_failover=True,
        tolerance=0.01,
        reference_history=lambda *_: (),
        store_history=stored.extend,
    )
    port.prepare_stock_history(CODES, DAY, DAY)
    with pytest.raises(DataFetchError) as error:
        port.stock_history(CODES[0], DAY, DAY)
    assert error.value.code == "MODEL_MARKET_UNVERIFIED_FAILOVER"
    assert stored == []


def test_preparation_batches_bound_calendar_day_rows():
    client = Client()
    source = TushareModelMarketSource(client)
    codes = tuple(f"{code:06}.SZ" for code in range(1, 26))
    source.prepare_stock_history(codes, date(2025, 8, 14), DAY)
    assert len(client.calls) == 6
    assert all(len(params["ts_code"].split(",")) <= 11 for _, params in client.calls)


def test_missing_batch_member_uses_individual_request():
    class Missing(Client):
        def daily(self, **kwargs):
            frame = super().daily(**kwargs)
            return frame.iloc[:1]

    client = Missing()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(CODES, DAY, DAY)
    assert source.stock_history(CODES[1], DAY, DAY)[0].asset_code == CODES[1]
    assert len(client.calls) == 4


def test_wide_scope_prefetches_by_session_and_retains_exact_stock_windows():
    codes = tuple(f"{code:06}.SZ" for code in range(1, 202))

    class MarketClient(Client):
        def daily(self, **kwargs):
            assert kwargs == {"trade_date": "20260918"}
            return super().daily(ts_code=",".join(codes))

        def adj_factor(self, **kwargs):
            assert kwargs == {"trade_date": "20260918"}
            return super().adj_factor(ts_code=",".join(codes))

    client = MarketClient()
    source = TushareModelMarketSource(client)
    source.prepare_stock_history(codes, DAY, DAY)
    assert len(client.calls) == 2
    assert all(source.stock_history(code, DAY, DAY)[0].asset_code == code for code in codes)
    assert len(client.calls) == 2


def test_truncated_session_prefetch_falls_back_without_partial_cache():
    class Truncated(Client):
        def daily(self, **kwargs):
            if "trade_date" in kwargs:
                return pd.concat([super().daily(ts_code=CODES[0])] * 6000)
            return super().daily(**kwargs)

        def adj_factor(self, **kwargs):
            return super().adj_factor(ts_code=kwargs.get("ts_code", CODES[0]))

    client = Truncated()
    source = TushareModelMarketSource(client)
    codes = tuple(f"{code:06}.SZ" for code in range(1, 202))
    source.prepare_stock_history(codes, DAY, DAY)
    assert len(source._prepared) == 201
    assert all(source.stock_history(code, DAY, DAY)[0].asset_code == code for code in codes)
