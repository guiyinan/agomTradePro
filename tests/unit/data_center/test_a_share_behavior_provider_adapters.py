"""Provider contracts for governed A-share trading-behavior indicators."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.provider_adapters import (
    AkshareUnifiedProviderAdapter,
    TushareUnifiedProviderAdapter,
)


def _config(source_type: str) -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name=source_type,
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


def test_akshare_collects_breadth_and_price_limit_counts(monkeypatch) -> None:
    today = date.today()
    ak = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(
            [
                {"代码": "600001", "名称": "甲公司", "涨跌幅": 1.2},
                {"代码": "000001", "名称": "乙公司", "涨跌幅": -0.5},
                {"代码": "300001", "名称": "ST丙公司", "涨跌幅": 3.0},
                {"代码": "688001", "名称": "丁公司", "涨跌幅": 0.0},
            ]
        ),
        stock_zt_pool_em=lambda date: pd.DataFrame(
            [{"代码": "600001", "名称": "甲公司"}, {"代码": "000002", "名称": "乙公司"}]
        ),
        stock_zt_pool_dtgc_em=lambda date: pd.DataFrame([{"代码": "300002", "名称": "戊公司"}]),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: ak,
    )
    adapter = AkshareUnifiedProviderAdapter(_config("akshare"))

    assert adapter.fetch_macro_series("CN_A_ADVANCE_COUNT", today, today)[0].value == 1
    assert adapter.fetch_macro_series("CN_A_DECLINE_COUNT", today, today)[0].value == 1
    assert adapter.fetch_macro_series("CN_A_LIMIT_UP_COUNT", today, today)[0].value == 2
    assert adapter.fetch_macro_series("CN_A_LIMIT_DOWN_COUNT", today, today)[0].value == 1


def test_akshare_behavior_missing_provider_rows_are_not_filled_with_zero(monkeypatch) -> None:
    today = date.today()
    ak = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(),
        stock_zt_pool_em=lambda date: pd.DataFrame(),
        stock_zt_pool_dtgc_em=lambda date: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: ak,
    )
    adapter = AkshareUnifiedProviderAdapter(_config("akshare"))

    for code in (
        "CN_A_ADVANCE_COUNT",
        "CN_A_DECLINE_COUNT",
        "CN_A_LIMIT_UP_COUNT",
        "CN_A_LIMIT_DOWN_COUNT",
    ):
        assert adapter.fetch_macro_series(code, today, today) == []


def test_tushare_collects_breadth_and_limit_counts(monkeypatch) -> None:
    observed_at = date(2026, 7, 30)

    class _Client:
        def daily(self, *, trade_date: str):
            assert trade_date == "20260730"
            return pd.DataFrame([{"pct_chg": 1.0}, {"pct_chg": -0.2}, {"pct_chg": 0.0}])

        def limit_list_d(self, *, trade_date: str, limit_type: str):
            assert trade_date == "20260730"
            return pd.DataFrame([{"ts_code": "600001.SH"}] * (2 if limit_type == "U" else 1))

    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda **kwargs: _Client(),
    )
    adapter = TushareUnifiedProviderAdapter(_config("tushare"))

    assert adapter.fetch_macro_series("CN_A_ADVANCE_COUNT", observed_at, observed_at)[0].value == 1
    assert adapter.fetch_macro_series("CN_A_DECLINE_COUNT", observed_at, observed_at)[0].value == 1
    assert adapter.fetch_macro_series("CN_A_LIMIT_UP_COUNT", observed_at, observed_at)[0].value == 2
    assert (
        adapter.fetch_macro_series("CN_A_LIMIT_DOWN_COUNT", observed_at, observed_at)[0].value == 1
    )


def test_tushare_empty_limit_response_does_not_publish_zero(monkeypatch) -> None:
    observed_at = date(2026, 7, 30)

    class _Client:
        def limit_list_d(self, *, trade_date: str, limit_type: str):
            return pd.DataFrame()

    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        lambda **kwargs: _Client(),
    )

    assert (
        TushareUnifiedProviderAdapter(_config("tushare")).fetch_macro_series(
            "CN_A_LIMIT_DOWN_COUNT", observed_at, observed_at
        )
        == []
    )
