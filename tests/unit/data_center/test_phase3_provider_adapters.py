"""Phase 3 provider adapter tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

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
    assert facts[0].source == "tushare-main"


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
    assert facts[0].source == "akshare-main"


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
    assert bars[0].source == "AKShare Public"
