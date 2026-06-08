"""Phase 3 provider adapter tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import requests

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.provider_adapters import (
    AkshareUnifiedProviderAdapter,
    FredUnifiedProviderAdapter,
    TushareUnifiedProviderAdapter,
    build_unified_provider_adapter,
)


def _config(source_type: str, name: str | None = None) -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name=name or source_type,
        source_type=source_type,
        is_active=True,
        priority=1,
        api_key="test-key",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_build_unified_provider_adapter_returns_expected_types():
    assert isinstance(
        build_unified_provider_adapter(_config("tushare")), TushareUnifiedProviderAdapter
    )
    assert isinstance(
        build_unified_provider_adapter(_config("akshare")), AkshareUnifiedProviderAdapter
    )
    assert isinstance(build_unified_provider_adapter(_config("fred")), FredUnifiedProviderAdapter)


def test_fred_unified_provider_adapter_parses_observations(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "observations": [
                    {"date": "2025-01-01", "value": "4.33"},
                    {"date": "2025-02-01", "value": "."},
                ]
            }

    def _fake_get(*args, **kwargs):
        return _Response()

    monkeypatch.setattr("apps.data_center.infrastructure.provider_adapters.requests.get", _fake_get)

    adapter = FredUnifiedProviderAdapter(_config("fred"))
    facts = adapter.fetch_macro_series("US_FED_FUNDS_RATE", date(2025, 1, 1), date(2025, 3, 1))

    assert len(facts) == 1
    assert facts[0].indicator_code == "US_FED_FUNDS_RATE"
    assert facts[0].value == 4.33
    assert facts[0].unit == "%"
    assert facts[0].source == "fred"
    assert facts[0].extra["provider_name"] == "fred"
    assert facts[0].extra["source_type"] == "fred"


def test_tushare_unified_provider_adapter_maps_fund_nav(monkeypatch):
    class _FakeAdapter:
        def __init__(self, token=None, http_url=None):
            self.token = token
            self.http_url = http_url

        def fetch_fund_daily(self, fund_code, start_date, end_date):
            return pd.DataFrame(
                [
                    {
                        "trade_date": pd.Timestamp("2025-03-01"),
                        "unit_nav": 1.234,
                        "accum_nav": 1.567,
                    }
                ]
            )

    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.tushare_fund_adapter.TushareFundAdapter",
        _FakeAdapter,
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "tushare-main"))
    facts = adapter.fetch_fund_nav("110011.OF", date(2025, 3, 1), date(2025, 3, 31))

    assert len(facts) == 1
    assert facts[0].fund_code == "110011.OF"
    assert facts[0].nav == 1.234
    assert facts[0].acc_nav == 1.567
    assert facts[0].source == "tushare"
    assert facts[0].extra["provider_name"] == "tushare-main"
    assert facts[0].extra["source_type"] == "tushare"


def test_tushare_unified_provider_adapter_fetches_etf_net_flow_from_size_delta(monkeypatch):
    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date):
            assert exchange == "SSE"
            assert start_date == "20260522"
            assert end_date == "20260601"
            return pd.DataFrame(
                [
                    {"cal_date": "20260529", "is_open": 1},
                    {"cal_date": "20260530", "is_open": 0},
                    {"cal_date": "20260601", "is_open": 1},
                ]
            )

        def etf_share_size(self, trade_date, exchange):
            values = {
                ("20260529", "SSE"): [100.0, 200.0],
                ("20260529", "SZSE"): [50.0],
                ("20260601", "SSE"): [110.0, 220.0],
                ("20260601", "SZSE"): [70.0],
            }
            return pd.DataFrame(
                [{"total_size": value} for value in values.get((trade_date, exchange), [])]
            )

    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda token=None, http_url=None: _FakePro(),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Proxy"))
    facts = adapter.fetch_macro_series(
        "CN_A_ETF_SIZE_FLOW",
        date(2026, 6, 1),
        date(2026, 6, 1),
    )

    assert len(facts) == 1
    assert facts[0].indicator_code == "CN_A_ETF_SIZE_FLOW"
    assert facts[0].reporting_period == date(2026, 6, 1)
    assert facts[0].value == 500_000.0
    assert facts[0].unit == "元"
    assert facts[0].extra["proxy"] == "tushare_etf_share_size_delta"
    assert facts[0].extra["flow_method"] == "etf_size_delta"


def test_akshare_unified_provider_adapter_maps_capital_flows(monkeypatch):
    class _FakeGateway:
        def get_capital_flows(self, asset_code, period="5d"):
            return [
                SimpleNamespace(
                    stock_code="000001.SZ",
                    trade_date=date(2025, 3, 7),
                    main_net_inflow=12.3,
                    main_net_ratio=1.2,
                    super_large_net_inflow=2.0,
                    large_net_inflow=3.0,
                    medium_net_inflow=4.0,
                    small_net_inflow=5.0,
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway.AKShareEastMoneyGateway",
        _FakeGateway,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "akshare-main"))
    facts = adapter.fetch_capital_flows("000001.SZ")

    assert len(facts) == 1
    assert facts[0].asset_code == "000001.SZ"
    assert facts[0].main_net == 12.3
    assert facts[0].extra["main_net_ratio"] == 1.2
    assert facts[0].source == "akshare"
    assert facts[0].extra["provider_name"] == "akshare-main"
    assert facts[0].extra["source_type"] == "akshare"


def test_akshare_etf_net_flow_falls_back_to_eastmoney_direct(monkeypatch):
    class _BrokenAkshare:
        def fund_etf_spot_em(self):
            raise ConnectionError("remote closed")

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "510300", "f14": "沪深300ETF", "f62": 1200.5, "f297": 20260605},
                        {"f12": "159915", "f14": "创业板ETF", "f62": -200.0, "f297": 20260605},
                    ],
                }
            }

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _BrokenAkshare(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.provider_adapters.requests.get",
        lambda *args, **kwargs: _Response(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series(
        "CN_A_ETF_NET_FLOW",
        date(2026, 6, 1),
        date(2026, 6, 8),
    )

    assert len(facts) == 1
    assert facts[0].indicator_code == "CN_A_ETF_NET_FLOW"
    assert facts[0].reporting_period == date(2026, 6, 5)
    assert facts[0].value == 1000.5
    assert facts[0].unit == "元"
    assert facts[0].source == "akshare"
    assert facts[0].extra["proxy"] == "eastmoney_clist_get"


def test_akshare_etf_net_flow_retries_eastmoney_direct(monkeypatch):
    class _BrokenAkshare:
        def fund_etf_spot_em(self):
            raise ConnectionError("remote closed")

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "total": 1,
                    "diff": [
                        {"f12": "510300", "f14": "沪深300ETF", "f62": 1200.5, "f297": 20260605},
                    ],
                }
            }

    calls = {"count": 0}

    def _flaky_get(*args, **kwargs):
        del args, kwargs
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.ConnectionError("remote closed")
        return _Response()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _BrokenAkshare(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.provider_adapters.requests.get",
        _flaky_get,
    )
    monkeypatch.setattr("apps.data_center.infrastructure.provider_adapters.sleep", lambda delay: None)

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series(
        "CN_A_ETF_NET_FLOW",
        date(2026, 6, 1),
        date(2026, 6, 8),
    )

    assert calls["count"] == 3
    assert len(facts) == 1
    assert facts[0].value == 1200.5


def test_akshare_price_history_preserves_requested_index_suffix(monkeypatch):
    class _FakeGateway:
        def get_historical_prices(self, asset_code, start_date, end_date):
            assert asset_code == "000300.SH"
            return [
                SimpleNamespace(
                    asset_code="000300",
                    trade_date=date(2026, 4, 21),
                    open=4750.0,
                    high=4776.0,
                    low=4722.0,
                    close=4768.0,
                    volume=1000,
                    amount=2000.0,
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway.AKShareEastMoneyGateway",
        _FakeGateway,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    bars = adapter.fetch_price_history("000300.SH", date(2026, 4, 1), date(2026, 4, 21))

    assert len(bars) == 1
    assert bars[0].asset_code == "000300.SH"
    assert bars[0].bar_date == date(2026, 4, 21)
    assert bars[0].source == "akshare"


def test_akshare_unified_provider_adapter_fetches_valuation_series(monkeypatch):
    class _FakeAkshare:
        def stock_zh_valuation_baidu(self, symbol, indicator, period):
            assert symbol == "001979"
            assert period == "近一年"
            values = {
                "市盈率(TTM)": 73.62,
                "市盈率(静)": 73.62,
                "市净率": 0.77,
                "总市值": 753.74,
            }
            return pd.DataFrame(
                [
                    {"date": "2026-04-24", "value": values[indicator]},
                    {"date": "2026-04-25", "value": values[indicator]},
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_valuations(
        "001979.SZ",
        date(2026, 4, 24),
        date(2026, 4, 25),
    )

    assert len(facts) == 2
    assert facts[0].asset_code == "001979.SZ"
    assert facts[0].val_date == date(2026, 4, 24)
    assert facts[0].pe_ttm == 73.62
    assert facts[0].pe_static == 73.62
    assert facts[0].pb == 0.77
    assert facts[0].market_cap == 753.74 * 100_000_000
    assert facts[0].source == "akshare"
    assert facts[0].extra["provider_name"] == "AKShare Public"
    assert facts[0].extra["source_type"] == "akshare"


def test_akshare_unified_provider_adapter_fetches_financial_facts(monkeypatch):
    class _FakeAkshare:
        def stock_financial_analysis_indicator_em(self, symbol, indicator):
            assert symbol == "001979.SZ"
            assert indicator == "按报告期"
            return pd.DataFrame(
                [
                    {
                        "REPORT_DATE": "2025-12-31 00:00:00",
                        "TOTALOPERATEREVE": 154_728_000_000.0,
                        "PARENTNETPROFIT": 1_023_784_000.0,
                        "TOTALOPERATEREVETZ": -13.53,
                        "PARENTNETPROFITTZ": -74.65,
                        "ROEJQ": 0.73,
                        "ZZCJLL": 0.083,
                        "ZCFZL": 67.5,
                        "LIABILITY": 564_032_300_000.0,
                    }
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_financials("001979.SZ", periods=8)
    by_metric = {fact.metric_code: fact for fact in facts}

    assert by_metric["revenue"].value == 154_728_000_000.0
    assert by_metric["net_profit"].value == 1_023_784_000.0
    assert by_metric["revenue_growth"].value == -13.53
    assert by_metric["net_profit_growth"].value == -74.65
    assert by_metric["roe"].value == 0.73
    assert by_metric["roa"].value == 0.083
    assert by_metric["debt_ratio"].value == 67.5
    assert by_metric["total_assets"].value == 564_032_300_000.0 / 0.675
    assert by_metric["equity"].value == by_metric["total_assets"].value - 564_032_300_000.0
    assert by_metric["revenue"].source == "akshare"
    assert by_metric["revenue"].extra["provider_name"] == "AKShare Public"
    assert by_metric["revenue"].extra["source_type"] == "akshare"


def test_akshare_unified_provider_adapter_fetches_market_turnover(monkeypatch):
    class _FakeAkshare:
        def stock_zh_index_daily_em(self, symbol):
            if symbol == "sh000001":
                return pd.DataFrame(
                    [{"date": "2026-05-19", "amount": 100.0}],
                )
            return pd.DataFrame(
                [{"date": "2026-05-19", "amount": 200.0}],
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert len(facts) == 1
    assert facts[0].value == 300.0
    assert facts[0].unit == "元"
    assert facts[0].extra["proxy"] == "sh_index_plus_sz_index"


def test_akshare_unified_provider_adapter_fetches_new_investor_accounts(monkeypatch):
    class _FakeAkshare:
        def stock_account_statistics_em(self):
            return pd.DataFrame(
                [
                    {"数据日期": "2026-03", "新增投资者-数量": 12.34},
                    {"数据日期": "2026-04", "新增投资者-数量": 23.45},
                    {"数据日期": "2026-05", "新增投资者-数量": None},
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series(
        "CN_A_NEW_INVESTOR_ACCOUNTS",
        date(2026, 3, 1),
        date(2026, 4, 30),
    )

    assert len(facts) == 2
    assert facts[0].reporting_period == date(2026, 3, 31)
    assert facts[0].value == 123_400.0
    assert facts[0].unit == "户"
    assert facts[1].reporting_period == date(2026, 4, 30)
    assert facts[1].value == 234_500.0
    assert facts[0].source == "akshare"
    assert facts[0].extra["proxy"] == "stock_account_statistics_em"
    assert facts[0].extra["original_unit"] == "万户"


def test_tushare_unified_provider_adapter_fetches_market_turnover(monkeypatch):
    class _FakePro:
        def index_daily(self, ts_code, start_date, end_date):
            assert start_date == "20260519"
            assert end_date == "20260519"
            if ts_code == "000001.SH":
                return pd.DataFrame([{"trade_date": "20260519", "amount": 100.0}])
            return pd.DataFrame([{"trade_date": "20260519", "amount": 200.0}])

    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda token=None, http_url=None: _FakePro(),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert len(facts) == 1
    assert facts[0].value == 300_000.0
    assert facts[0].unit == "元"
    assert facts[0].extra["proxy"] == "tushare_index_daily_sh000001_plus_sz399001"
    assert facts[0].extra["original_unit"] == "千元"


def test_tushare_unified_provider_adapter_fetches_margin_balance(monkeypatch):
    class _FakePro:
        def margin(self, start_date, end_date):
            assert start_date == "20260519"
            assert end_date == "20260519"
            return pd.DataFrame(
                [
                    {"trade_date": "20260519", "rzye": 100.0, "exchange_id": "SSE"},
                    {"trade_date": "20260519", "rzye": 200.0, "exchange_id": "SZSE"},
                ]
            )

    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda token=None, http_url=None: _FakePro(),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_MARGIN_BALANCE", date(2026, 5, 19), date(2026, 5, 19))

    assert len(facts) == 1
    assert facts[0].value == 300.0
    assert facts[0].unit == "元"
    assert facts[0].extra["proxy"] == "tushare_margin_sum_rzye"


def test_akshare_unified_provider_adapter_fetches_market_news(monkeypatch):
    class _FakeGateway:
        def get_market_news(self, limit=20):
            assert limit == 2
            return [
                SimpleNamespace(
                    title="市场回暖",
                    content="市场回暖，资金净流入，情绪走强",
                    published_at=datetime(2026, 5, 19, 9, 30, tzinfo=UTC),
                    url="https://example.com/news/1",
                    news_id="m1",
                )
            ]

        def get_stock_news(self, asset_code, limit=20):
            raise AssertionError("stock news path should not be used for market scope")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway.AKShareEastMoneyGateway",
        _FakeGateway,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_news("", limit=2)

    assert len(facts) == 1
    assert facts[0].asset_code == ""
    assert facts[0].sentiment_score and facts[0].sentiment_score > 0
    assert facts[0].extra["market_scope"] == "broad_market"
