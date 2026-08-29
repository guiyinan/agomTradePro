"""Phase 3 provider adapter tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.macro_sources.base import DataSourceUnavailableError
from apps.data_center.infrastructure.macro_sources.fetchers.base_fetchers import (
    BaseIndicatorFetcher,
)
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


def test_tushare_unified_provider_uses_its_own_transport_configuration(monkeypatch):
    captured: dict[str, object] = {}
    expected_client = SimpleNamespace()

    def create_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return expected_client

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        create_client,
    )
    config = replace(
        _config("tushare", "tushare-relay"),
        api_key="relay-token",
        http_url="https://relay.example.test/tushare/pro",
        extra_config={"tushare_request_mode": "unified_relay"},
    )

    client = TushareUnifiedProviderAdapter(config)._create_pro_client()

    assert client is expected_client
    assert captured == {
        "token": "relay-token",
        "http_url": "https://relay.example.test/tushare/pro",
        "request_mode": "unified_relay",
    }


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

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_specialized.requests.get",
        _fake_get,
    )

    adapter = FredUnifiedProviderAdapter(_config("fred"))
    facts = adapter.fetch_macro_series("US_FED_FUNDS_RATE", date(2025, 1, 1), date(2025, 3, 1))

    assert len(facts) == 1
    assert facts[0].indicator_code == "US_FED_FUNDS_RATE"
    assert facts[0].value == 4.33
    assert facts[0].unit == "%"
    assert facts[0].source == "fred"
    assert facts[0].extra["provider_name"] == "fred"
    assert facts[0].extra["source_type"] == "fred"


def test_akshare_macro_source_failure_is_recoverable_connection_error(monkeypatch):
    class _BrokenMacroAdapter:
        def fetch(self, indicator_code, start_date, end_date):
            raise DataSourceUnavailableError("postgresql://user:secret@provider.invalid/data")

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_akshare.AKShareAdapter",
        lambda: _BrokenMacroAdapter(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare"))

    try:
        adapter.fetch_macro_series("CN_CPI_NATIONAL_YOY", date(2026, 5, 1), date(2026, 6, 1))
    except ConnectionError as exc:
        assert str(exc) == "macro_source_unavailable"
        assert "secret" not in str(exc)
    else:
        raise AssertionError("Expected ConnectionError")


def test_cpi_detailed_string_and_numeric_percentages_have_identical_scale(monkeypatch):
    def fetch(value):
        ak = SimpleNamespace(
            macro_china_cpi=lambda: pd.DataFrame([{"月份": "2026年6月", "全国-同比增长": value}])
        )
        fetcher = BaseIndicatorFetcher(
            ak,
            "akshare",
            validate_fn=lambda point: None,
            sort_dedup_fn=lambda points: points,
        )
        return fetcher.fetch_cpi_detailed(
            date(2026, 6, 1),
            date(2026, 6, 30),
            "CN_CPI_NATIONAL_YOY",
        )[0]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.base_fetchers.resolve_indicator_units",
        lambda code: ("%", "%"),
    )

    assert fetch("1.0%").value == fetch(1.0).value == 1.0


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
        "apps.data_center.infrastructure._provider_adapter_tushare.build_tushare_fund_adapter",
        lambda **kwargs: _FakeAdapter(**kwargs),
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


def test_tushare_unified_provider_adapter_builds_typed_financial_facts(monkeypatch):
    record = SimpleNamespace(
        stock_code="001979.SZ",
        report_date=date(2025, 12, 31),
        report_type="4Q",
        revenue=154_728_000_000.0,
        net_profit=1_023_784_000.0,
        total_assets=835_603_407_407.0,
        total_liabilities=564_032_300_000.0,
        equity=271_571_107_407.0,
        roe=0.73,
        roa=0.083,
        debt_ratio=67.5,
        revenue_growth=-13.53,
        net_profit_growth=-74.65,
    )
    gateway = SimpleNamespace(fetch=lambda asset_code, periods: SimpleNamespace(records=[record]))
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.build_tushare_financial_gateway",
        lambda **kwargs: gateway,
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "tushare-main"))
    facts = adapter.fetch_financials("001979.SZ", periods=8)
    by_metric = {fact.metric_code: fact for fact in facts}

    assert len(facts) == 10
    assert by_metric["revenue"].period_end == date(2025, 12, 31)
    assert by_metric["revenue"].period_type.value == "annual"
    # The compatibility gateway exposes a period end, not a source announcement
    # boundary; it must remain unavailable for PIT publication rather than
    # treating period_end as available_at.
    assert by_metric["revenue"].available_at is None
    assert by_metric["revenue"].unit == "元"
    assert by_metric["roa"].value == 0.083
    assert by_metric["net_profit_growth"].value == -74.65
    assert by_metric["revenue"].source == "tushare"
    assert by_metric["revenue"].extra["provider_name"] == "tushare-main"


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

        def etf_share_size(self, start_date, end_date, exchange):
            assert start_date == "20260529"
            assert end_date == "20260601"
            values = {
                "SSE": [
                    {"trade_date": "20260529", "total_size": 100.0},
                    {"trade_date": "20260529", "total_size": 200.0},
                    {"trade_date": "20260601", "total_size": 110.0},
                    {"trade_date": "20260601", "total_size": 220.0},
                ],
                "SZSE": [
                    {"trade_date": "20260529", "total_size": 50.0},
                    {"trade_date": "20260601", "total_size": 70.0},
                ],
            }
            return pd.DataFrame(values.get(exchange, []))

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: _FakePro(),
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
    assert facts[0].value == 50.0
    assert facts[0].unit == "万元"
    assert facts[0].extra["proxy"] == "tushare_etf_share_size_delta"
    assert facts[0].extra["flow_method"] == "etf_size_delta"


def test_tushare_etf_size_flow_fails_closed_when_one_exchange_is_missing(monkeypatch):
    """A partial exchange snapshot must never masquerade as total ETF size."""

    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date):
            return pd.DataFrame(
                [
                    {"cal_date": "20260529", "is_open": 1},
                    {"cal_date": "20260601", "is_open": 1},
                ]
            )

        def etf_share_size(self, start_date, end_date, exchange):
            del start_date, end_date
            if exchange == "SZSE":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {"trade_date": "20260529", "total_size": 100.0},
                    {"trade_date": "20260601", "total_size": 110.0},
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: _FakePro(),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Proxy"))

    assert (
        adapter.fetch_macro_series(
            "CN_A_ETF_SIZE_FLOW",
            date(2026, 6, 1),
            date(2026, 6, 1),
        )
        == []
    )


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
        "apps.data_center.infrastructure._provider_adapter_akshare.requests.get",
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
        "apps.data_center.infrastructure._provider_adapter_akshare.requests.get",
        _flaky_get,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_akshare.sleep",
        lambda delay: None,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series(
        "CN_A_ETF_NET_FLOW",
        date(2026, 6, 1),
        date(2026, 6, 8),
    )

    assert calls["count"] == 3
    assert len(facts) == 1
    assert facts[0].value == 1200.5


def test_akshare_etf_net_flow_permission_denied_fast_fails(monkeypatch):
    class _BrokenAkshare:
        def fund_etf_spot_em(self):
            raise ConnectionError("remote closed")

    calls = {"count": 0, "sleep_count": 0}

    def _blocked_get(*args, **kwargs):
        del args, kwargs
        calls["count"] += 1
        raise requests.ConnectionError("[WinError 10013] socket access forbidden")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _BrokenAkshare(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_akshare.requests.get",
        _blocked_get,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_akshare.sleep",
        lambda delay: calls.__setitem__("sleep_count", calls["sleep_count"] + 1),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))

    try:
        adapter.fetch_macro_series(
            "CN_A_ETF_NET_FLOW",
            date(2026, 6, 1),
            date(2026, 6, 8),
        )
    except ConnectionError as exc:
        assert "10013" in str(exc)
    else:
        raise AssertionError("permission-denied ETF fetch should raise ConnectionError")

    assert calls["count"] == 1
    assert calls["sleep_count"] == 0


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


def test_akshare_price_history_preserves_fallback_source(monkeypatch):
    class _FallbackGateway:
        def get_historical_prices(self, asset_code, start_date, end_date):
            return [
                SimpleNamespace(
                    trade_date=date(2026, 4, 21),
                    open=10.0,
                    high=11.0,
                    low=9.0,
                    close=10.5,
                    volume=1000,
                    amount=2000.0,
                    source="tencent",
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway.AKShareEastMoneyGateway",
        _FallbackGateway,
    )

    bars = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public")).fetch_price_history(
        "000001.SZ", date(2026, 4, 1), date(2026, 4, 21)
    )

    assert bars[0].source == "tencent"


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


def test_akshare_current_valuation_batch_preserves_tencent_provenance(monkeypatch):
    from apps.data_center.infrastructure.market_gateway_entities import ValuationSnapshot

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway.get_valuation_snapshots",
        lambda _self, _codes: [
            ValuationSnapshot(
                stock_code="000001.SZ",
                observed_at=datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
                pe_ttm=5.24,
                pb=0.49,
                market_cap=225_691_000_000.0,
                float_market_cap=225_687_000_000.0,
                source="tencent",
            )
        ],
    )

    facts = AkshareUnifiedProviderAdapter(
        _config("akshare", "AKShare Public")
    ).fetch_current_valuations(["000001.SZ"], date(2026, 7, 31))

    assert len(facts) == 1
    assert facts[0].source == "tencent"
    assert facts[0].val_date == date(2026, 7, 31)
    assert facts[0].extra["actual_source"] == "tencent"
    assert facts[0].extra["provider_name"] == "AKShare Public"


def test_akshare_current_valuation_batch_chunks_tencent_requests(monkeypatch):
    from apps.data_center.infrastructure.market_gateway_entities import ValuationSnapshot

    batches: list[list[str]] = []

    def _fetch(_self, codes):
        batches.append(list(codes))
        return [
            ValuationSnapshot(
                stock_code=code,
                observed_at=datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
                pe_ttm=5.24,
                pb=0.49,
                market_cap=1.0,
                float_market_cap=1.0,
                source="tencent",
            )
            for code in codes
        ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway."
        "TencentGateway.get_valuation_snapshots",
        _fetch,
    )
    asset_codes = [f"{index:06d}.SZ" for index in range(401)]

    facts = AkshareUnifiedProviderAdapter(
        _config("akshare", "AKShare Public")
    ).fetch_current_valuations(asset_codes, date(2026, 7, 31))

    assert [len(batch) for batch in batches] == [200, 200, 1]
    assert len(facts) == 401


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
    assert (
        by_metric["total_assets"].extra["derived_from"] == "total_liabilities_divided_by_debt_ratio"
    )
    assert by_metric["equity"].extra["derived_from"] == "total_assets_minus_total_liabilities"
    assert by_metric["revenue"].source == "akshare"
    assert by_metric["revenue"].extra["provider_name"] == "AKShare Public"
    assert by_metric["revenue"].extra["source_type"] == "akshare"
    assert by_metric["revenue"].report_date is None
    assert by_metric["revenue"].available_at is None


def test_akshare_financials_preserve_partial_metrics_and_notice_date(monkeypatch):
    """Missing ratios must not erase valid facts or create synthetic zeroes."""

    class _FakeAkshare:
        def stock_financial_analysis_indicator_em(self, symbol, indicator):
            return pd.DataFrame(
                [
                    {
                        "REPORT_DATE": "2025-12-31 00:00:00",
                        "NOTICE_DATE": "2026-03-31 00:00:00",
                        "TOTALOPERATEREVE": 1_000_000.0,
                    }
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_financials("001979.SZ")

    assert [(fact.metric_code, fact.value) for fact in facts] == [("revenue", 1_000_000.0)]
    assert facts[0].period_end == date(2025, 12, 31)
    assert facts[0].report_date == date(2026, 3, 31)
    assert facts[0].available_at == datetime(2026, 3, 31, tzinfo=UTC)
    assert "derived_from" not in facts[0].extra


@pytest.mark.parametrize("periods", [0, -1, True])
def test_akshare_financials_reject_invalid_periods_before_provider_access(
    monkeypatch,
    periods,
):
    """Invalid fetch bounds fail before loading the external SDK."""

    provider_calls = 0

    def get_provider():
        nonlocal provider_calls
        provider_calls += 1
        return object()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        get_provider,
    )
    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))

    with pytest.raises(ValueError, match="periods must be a positive integer"):
        adapter.fetch_financials("001979.SZ", periods=periods)

    assert provider_calls == 0


def test_akshare_unified_provider_adapter_fetches_market_turnover(monkeypatch):
    class _FakeAkshare:
        def stock_sse_deal_daily(self, date):
            assert date == "20260519"
            return pd.DataFrame(
                [{"单日情况": "成交金额", "主板A": 100.0, "科创板": 50.0}],
            )

        def stock_szse_summary(self, date):
            assert date == "20260519"
            return pd.DataFrame(
                [
                    {"证券类别": "主板A股", "成交金额": 20_000_000_000.0},
                    {"证券类别": "创业板A股", "成交金额": 10_000_000_000.0},
                    {"证券类别": "主板B股", "成交金额": 999.0},
                ],
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert len(facts) == 1
    assert facts[0].value == 45_000_000_000.0
    assert facts[0].unit == "元"
    assert facts[0].extra["aggregation"] == "sse_a_share_plus_szse_a_share_official_summary"


def test_akshare_unified_provider_adapter_rejects_tencent_index_proxy_for_turnover(
    monkeypatch,
):
    class _FakeAkshare:
        def stock_zh_index_daily_em(self, symbol):
            del symbol
            raise requests.RequestException("eastmoney blocked")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )
    monkeypatch.setattr(
        AkshareUnifiedProviderAdapter,
        "_fetch_market_turnover_from_eastmoney_quote",
        lambda self, target_date: [],
    )

    class _FakeTencentGateway:
        def __init__(self, timeout=15.0):
            self.timeout = timeout

        def get_historical_prices(self, asset_code, start_date, end_date):
            assert start_date == "20260519"
            assert end_date == "20260519"
            if asset_code == "000001.SH":
                return [
                    SimpleNamespace(
                        trade_date=date(2026, 5, 19),
                        amount=1000.0,
                    )
                ]
            return [
                SimpleNamespace(
                    trade_date=date(2026, 5, 19),
                    amount=2000.0,
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        _FakeTencentGateway,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


def test_akshare_unified_provider_adapter_rejects_eastmoney_index_proxy_for_turnover(
    monkeypatch,
):
    class _FakeAkshare:
        def stock_zh_index_daily_em(self, symbol):
            del symbol
            raise requests.RequestException("eastmoney blocked")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )

    class _FakeResponse:
        def __init__(self, amount):
            self._amount = amount

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"f48": self._amount}}

    class _FakeSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None, timeout=10):
            del url, timeout
            if params["secid"] == "1.000001":
                return _FakeResponse(1000.0)
            return _FakeResponse(2000.0)

    class _NoOpContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway._eastmoney_direct_network",
        lambda: _NoOpContext(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_base.requests.Session",
        _FakeSession,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


def test_akshare_unified_provider_adapter_fast_fails_turnover_when_quotes_blocked(
    monkeypatch,
):
    class _FakeAkshare:
        def stock_zh_index_daily_em(self, symbol):
            del symbol
            raise requests.RequestException("eastmoney blocked")

    class _BlockedSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None, timeout=10):
            del url, params, timeout
            raise requests.ConnectionError("[WinError 10013] socket access forbidden")

    class _NoOpContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway._eastmoney_direct_network",
        lambda: _NoOpContext(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_base.requests.Session",
        _BlockedSession,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        lambda timeout=15.0: (_ for _ in ()).throw(AssertionError("tencent should be skipped")),
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


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


def test_akshare_unified_provider_adapter_falls_back_to_sse_account_openings(monkeypatch):
    class _FakeAkshare:
        def stock_account_statistics_em(self):
            return pd.DataFrame([{"数据日期": "2023-08", "新增投资者-数量": 99.59}])

    class _NoOpContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "result": [
                    {
                        "TERM": "2026.05",
                        "TOTAL": "298.44",
                        "A_ACCT": "276.53",
                        "B_ACCT": "0.08",
                        "FUND_ACCT": "21.83",
                    }
                ]
            }

    seen_requests = []

    def _fake_get(url, params=None, headers=None, timeout=None):
        seen_requests.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        return _FakeResponse()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: _FakeAkshare(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway._eastmoney_direct_network",
        lambda: _NoOpContext(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.sse_investor_accounts.requests.get",
        _fake_get,
    )

    adapter = AkshareUnifiedProviderAdapter(_config("akshare", "AKShare Public"))
    facts = adapter.fetch_macro_series(
        "CN_A_NEW_INVESTOR_ACCOUNTS",
        date(2023, 8, 1),
        date(2026, 5, 31),
    )

    assert [fact.reporting_period for fact in facts] == [
        date(2023, 8, 31),
        date(2026, 5, 31),
    ]
    assert facts[1].value == 2_984_400.0
    assert facts[1].unit == "户"
    assert facts[1].source == "akshare"
    assert facts[1].extra["proxy"] == "sse_monthly_all_account_openings"
    assert facts[1].extra["original_unit"] == "万户"
    assert facts[1].extra["raw_total_account_openings"] == 298.44
    assert facts[1].extra["source_sql_id"] == "COMMON_SSE_TZZ_M_ALL_ACCT_C"
    assert seen_requests[0]["params"]["MDATE"] == "202605"


def test_tushare_unified_provider_adapter_fetches_market_turnover(monkeypatch):
    class _FakePro:
        def trade_cal(self, exchange, start_date, end_date, is_open):
            assert exchange == ""
            assert start_date == "20260519"
            assert end_date == "20260519"
            assert is_open == "1"
            return pd.DataFrame([{"cal_date": "20260519", "is_open": 1}])

        def daily(self, trade_date):
            assert trade_date == "20260519"
            return pd.DataFrame(
                [
                    {"trade_date": "20260519", "ts_code": "600000.SH", "amount": 100.0},
                    {"trade_date": "20260519", "ts_code": "000001.SZ", "amount": 200.0},
                ]
            )

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: _FakePro(),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert len(facts) == 1
    assert facts[0].value == 300.0
    assert facts[0].unit == "千元"
    assert facts[0].extra["aggregation"] == "tushare_a_share_daily_amount_sum"
    assert facts[0].extra["original_unit"] == "千元"


def test_tushare_unified_provider_adapter_rejects_tencent_index_proxy_for_turnover(
    monkeypatch,
):
    class _FakeTencentGateway:
        def __init__(self, timeout=15.0):
            self.timeout = timeout

        def get_historical_prices(self, asset_code, start_date, end_date):
            assert start_date == "20260519"
            assert end_date == "20260519"
            if asset_code == "000001.SH":
                return [
                    SimpleNamespace(
                        trade_date=date(2026, 5, 19),
                        amount=1500.0,
                    )
                ]
            return [
                SimpleNamespace(
                    trade_date=date(2026, 5, 19),
                    amount=2500.0,
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("tushare timeout")),
    )
    monkeypatch.setattr(
        TushareUnifiedProviderAdapter,
        "_fetch_market_turnover_from_eastmoney_quote",
        lambda self, target_date: [],
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        _FakeTencentGateway,
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


def test_tushare_unified_provider_adapter_rejects_eastmoney_index_proxy_for_turnover(
    monkeypatch,
):
    class _FakeResponse:
        def __init__(self, amount):
            self._amount = amount

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"f48": self._amount}}

    class _FakeSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None, timeout=10):
            del url, timeout
            if params["secid"] == "1.000001":
                return _FakeResponse(1500.0)
            return _FakeResponse(2500.0)

    class _NoOpContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("tushare timeout")),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway._eastmoney_direct_network",
        lambda: _NoOpContext(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_base.requests.Session",
        _FakeSession,
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


def test_tushare_unified_provider_adapter_fast_fails_turnover_when_quotes_blocked(
    monkeypatch,
):
    class _BlockedSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None, timeout=10):
            del url, params, timeout
            raise requests.ConnectionError("[WinError 10013] socket access forbidden")

    class _NoOpContext:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("tushare timeout")),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway._eastmoney_direct_network",
        lambda: _NoOpContext(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure._provider_adapter_base.requests.Session",
        _BlockedSession,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        lambda timeout=15.0: (_ for _ in ()).throw(AssertionError("tencent should be skipped")),
    )

    adapter = TushareUnifiedProviderAdapter(_config("tushare", "Tushare Pro"))
    facts = adapter.fetch_macro_series("CN_A_TOTAL_TURNOVER", date(2026, 5, 19), date(2026, 5, 19))

    assert facts == []


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
        "apps.data_center.infrastructure._provider_adapter_tushare.create_tushare_pro_client",
        lambda **_kwargs: _FakePro(),
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
