"""Gateway history must retain its adjustment basis in canonical storage."""

from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest

from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.alpha_price_coverage_sync import AlphaPriceCoverageSyncService
from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
    AKShareEastMoneyGateway,
)
from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway


@pytest.fixture(autouse=True)
def configured_tencent_history_units(monkeypatch):
    monkeypatch.setattr(
        "apps.data_center.infrastructure.tencent_history_units.get_runtime_config_value",
        lambda key: '{"*": 100, "688.SH": 1, "689.SH": 1}',
    )


@pytest.mark.parametrize("code", ["688012.SH", "689009.SH"])
def test_tencent_star_history_is_already_shares(monkeypatch, code):
    response = Mock()
    response.json.return_value = {
        "data": {
            "sh"
            + code[:6]: {
                "day": [["2026-09-18", "357.6", "354.92", "362", "350.83", "20605046.000"]]
            }
        }
    }
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        lambda *args, **kwargs: response,
    )
    bars = TencentGateway().get_historical_prices(
        code, "20260918", "20260918", price_adjustment=PriceAdjustment.NONE
    )
    assert bars[0].volume == 20605046


@pytest.mark.parametrize(
    "key,adjustment", [("qfqday", PriceAdjustment.FORWARD), ("day", PriceAdjustment.NONE)]
)
def test_tencent_history_retains_basis_and_canonical_volume(monkeypatch, key, adjustment):
    response = Mock()
    response.json.return_value = {
        "data": {
            "sz000001": {
                key: [["2025-08-14", "11.674", "11.604", "11.744", "11.594", "1241041.29"]]
            }
        }
    }
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        Mock(return_value=response),
    )
    bars = TencentGateway().get_historical_prices("000001.SZ", "20250814", "20250814")
    assert bars[0].adjustment == adjustment
    assert bars[0].volume == 124104129
    stored = AlphaPriceCoverageSyncService._normalize_price_bars(
        asset_code="000001.SZ",
        bars=bars,
        start_date=date(2025, 8, 14),
        end_date=date(2025, 8, 14),
    )
    assert stored[0].adjustment == adjustment
    assert stored[0].volume == 124104129


def test_eastmoney_history_retains_qfq_and_converts_lots_to_shares():
    bars = AKShareEastMoneyGateway(request_interval_sec=0)._parse_em_cn_bars(
        pd.DataFrame(
            [
                {
                    "日期": "2025-08-14",
                    "开盘": 10,
                    "最高": 11,
                    "最低": 9,
                    "收盘": 10,
                    "成交量": 12.34,
                    "成交额": 12340,
                }
            ]
        ),
        "000001.SZ",
        "eastmoney",
    )
    assert bars[0].adjustment == PriceAdjustment.FORWARD
    assert bars[0].volume == 1234


@pytest.mark.parametrize("raw_available", [True, False])
def test_explicit_raw_history_never_substitutes_adjusted_rows(monkeypatch, raw_available):
    payload = {"qfqday": [["2025-08-14", "11.674", "11.604", "11.744", "11.594", "1241041"]]}
    if raw_available:
        payload["day"] = [["2025-08-14", "12.27", "12.2", "12.34", "12.19", "1241041"]]
    response = Mock()
    response.json.return_value = {"data": {"sz000001": payload}}
    fetch = Mock(return_value=response)
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get", fetch
    )
    bars = TencentGateway().get_historical_prices(
        "000001.SZ", "20250814", "20250814", price_adjustment=PriceAdjustment.NONE
    )
    assert fetch.call_args.kwargs["params"]["param"].endswith(",1000,")
    if raw_available:
        assert bars[0].adjustment == PriceAdjustment.NONE
        assert bars[0].close == 12.2
        assert bars[0].volume == 124104100
    else:
        assert bars == []


def test_alpha_sync_does_not_collapse_different_adjustment_bases():
    from dataclasses import replace

    from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar

    raw = HistoricalPriceBar(
        "000001.SZ", date(2025, 8, 14), 12.27, 12.34, 12.19, 12.20, source="tencent"
    )
    adjusted = replace(
        raw, close=11.604, open=11.674, high=11.744, low=11.594, adjustment=PriceAdjustment.FORWARD
    )
    stored = AlphaPriceCoverageSyncService._normalize_price_bars(
        asset_code="000001.SZ",
        bars=[raw, adjusted],
        start_date=raw.trade_date,
        end_date=raw.trade_date,
    )
    assert len(stored) == 2
    assert {bar.adjustment for bar in stored} == {PriceAdjustment.NONE, PriceAdjustment.FORWARD}


def test_tushare_fallback_preserves_adjustment_in_canonical_adapter(monkeypatch):
    from apps.data_center.domain.entities import ProviderConfig
    from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
    from apps.data_center.infrastructure.provider_adapters import TushareUnifiedProviderAdapter

    bar = HistoricalPriceBar(
        "000001.SZ",
        date(2025, 8, 14),
        10,
        11,
        9,
        10,
        volume=1234,
        source="tencent",
        adjustment=PriceAdjustment.FORWARD,
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.TushareGateway",
        lambda **kw: Mock(get_historical_prices=Mock(return_value=[bar])),
    )
    config = ProviderConfig(
        id=1,
        name="Tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    stored = TushareUnifiedProviderAdapter(config).fetch_price_history(
        bar.asset_code,
        bar.trade_date,
        bar.trade_date,
    )
    assert stored[0].adjustment == PriceAdjustment.FORWARD
    assert stored[0].source == "tencent"
    assert stored[0].volume == 1234


def test_tushare_history_converts_vendor_units(monkeypatch):
    from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

    client = Mock()
    client.daily.return_value = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20250814",
                "open": 12.27,
                "high": 12.34,
                "low": 12.19,
                "close": 12.20,
                "vol": 1241041.29,
                "amount": 1523447.932,
            },
        ]
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **kw: client,
    )
    bars = TushareGateway().get_historical_prices("000001.SZ", "20250814", "20250814")
    assert bars[0].adjustment == PriceAdjustment.NONE
    assert bars[0].volume == 124104129
    assert bars[0].amount == pytest.approx(1523447932)


def test_model_reference_excludes_forward_adjusted_history():
    from apps.data_center.domain.entities import PriceBar
    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service
    from tests.unit.data_center.test_model_market_data import D1, D2, Source, bar

    class Provider(Source):
        def provider_name(self):
            return "primary"

        def provider_source(self):
            return "tushare"

        def model_market_source(self, **kwargs):
            return self

    adjusted = PriceBar(
        asset_code="600000.SH",
        bar_date=D1,
        open=5,
        high=5,
        low=5,
        close=5,
        volume=1200,
        source="old",
        adjustment=PriceAdjustment.FORWARD,
    )
    raw = PriceBar(
        asset_code="600000.SH",
        bar_date=D1,
        open=10,
        high=10,
        low=10,
        close=10,
        volume=1200,
        source="old",
        adjustment=PriceAdjustment.NONE,
    )
    repository = Mock(get_bars=Mock(return_value=[raw, adjusted]))
    service = build_model_market_service(
        Mock(get_providers=Mock(return_value=[Provider((bar(), bar(D2)))])),
        repository,
        {
            "status": "active",
            "enable_failover": True,
            "default_source": "tushare",
            "failover_tolerance": 0.01,
        },
    )
    result = service.stock_history("600000.SH", D1, D2)
    assert result[-1].trade_date == D2
    repository.bulk_upsert.assert_called_once()


@pytest.mark.parametrize(
    "volume,reason",
    [(None, "MODEL_MARKET_UNVERIFIED_FAILOVER"), (0, "MODEL_MARKET_SOURCE_CONFLICT"), (1200, None)],
)
def test_missing_volume_is_not_fabricated_as_zero_reference(volume, reason):
    from apps.data_center.domain.entities import PriceBar
    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service
    from core.exceptions import DataFetchError
    from tests.unit.data_center.test_model_market_data import D1, D2, Source, bar

    class Provider(Source):
        def provider_name(self):
            return "backup"

        def provider_source(self):
            return "tushare"

        def model_market_source(self, **kwargs):
            return self

    reference = PriceBar(
        asset_code="600000.SH",
        bar_date=D1,
        open=10,
        high=10,
        low=10,
        close=10,
        volume=volume,
        source="old",
        adjustment=PriceAdjustment.NONE,
    )
    repository = Mock(get_bars=Mock(return_value=[reference]))
    service = build_model_market_service(
        Mock(get_providers=Mock(return_value=[Provider((bar(), bar(D2)))])),
        repository,
        {
            "status": "active",
            "enable_failover": True,
            "default_source": "akshare",
            "failover_tolerance": 0.01,
        },
    )
    if reason:
        with pytest.raises(DataFetchError) as caught:
            service.stock_history("600000.SH", D1, D2)
        assert caught.value.code == reason
        repository.bulk_upsert.assert_not_called()
    else:
        assert service.stock_history("600000.SH", D1, D2)[-1].trade_date == D2
