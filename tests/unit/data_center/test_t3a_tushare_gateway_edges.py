"""T3A Tushare gateway conversion, routing, and fallback contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.infrastructure.gateways import tushare_gateway


def test_tushare_scalar_and_code_helpers() -> None:
    assert tushare_gateway._safe_decimal(None) is None
    assert tushare_gateway._safe_decimal("bad") is None
    assert tushare_gateway._safe_decimal(float("nan")) is None
    assert tushare_gateway._safe_int(None) is None
    assert tushare_gateway._safe_int("bad") is None
    assert tushare_gateway.TushareGateway._to_tushare_code("600000") == "600000.SH"
    assert tushare_gateway.TushareGateway._to_tushare_code("000001") == "000001.SZ"
    assert tushare_gateway.TushareGateway._to_tushare_code("510300") == "510300.SH"
    assert tushare_gateway.TushareGateway._to_tushare_code("159919") == "159919.SZ"
    assert tushare_gateway.TushareGateway._to_tushare_code("BOND") == "BOND.SH"
    assert tushare_gateway.TushareGateway._is_index_asset("000300.SH")
    assert tushare_gateway.TushareGateway._is_index_asset("399001.SZ")
    assert not tushare_gateway.TushareGateway._is_index_asset("000001.SZ")


def test_quote_path_skips_empty_invalid_and_isolates_per_code_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Adapter:
        def fetch_daily_data(self, *, stock_code: str, **_kwargs: str) -> pd.DataFrame:
            if stock_code == "error":
                raise RuntimeError("single failure")
            if stock_code == "empty":
                return pd.DataFrame()
            if stock_code == "invalid":
                return pd.DataFrame([{"close": 0}])
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240102",
                        "close": 12,
                        "pre_close": 10,
                        "vol": "100",
                        "amount": 200,
                        "turnover_rate": 3,
                        "high": 13,
                        "low": 9,
                        "open": 10,
                    }
                ]
            )

    monkeypatch.setattr(tushare_gateway, "build_tushare_stock_adapter", lambda: _Adapter())
    result = tushare_gateway.TushareGateway().get_quote_snapshots(
        ["empty", "invalid", "error", "000001.SZ"]
    )
    assert len(result) == 1
    assert result[0].change_pct == 20
    assert result[0].volume == 10_000
    assert result[0].amount == 200_000

    monkeypatch.setattr(
        tushare_gateway,
        "build_tushare_stock_adapter",
        lambda: (_ for _ in ()).throw(RuntimeError("batch failure")),
    )
    assert tushare_gateway.TushareGateway().get_quote_snapshots(["000001.SZ"]) == []


def test_native_quote_path_uses_full_market_session_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    class _Pro:
        def daily(self, **kwargs: str) -> pd.DataFrame:
            calls.append(kwargs)
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260924",
                        "close": 12,
                        "pre_close": 10,
                        "vol": 100,
                        "amount": 200,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260924",
                        "close": 9,
                        "pre_close": 9,
                        "vol": 300,
                        "amount": 400,
                    },
                ]
            )

    monkeypatch.setattr(tushare_gateway, "build_tushare_stock_adapter", lambda: None)
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: _Pro(),
    )

    result = tushare_gateway.TushareGateway().get_quote_snapshots(
        ["000001.SZ", "600000.SH"], target_trade_date=date(2026, 9, 24)
    )

    assert [item.stock_code for item in result] == ["000001.SZ", "600000.SH"]
    assert result[0].volume == 10_000
    assert result[0].amount == 200_000
    assert len(calls) == 1
    assert set(calls[0]) == {"trade_date"}


def test_native_quote_authorization_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Pro:
        def daily(self, **_kwargs: str) -> pd.DataFrame:
            raise tushare_gateway.TushareRelayAuthorizationError("HTTP 403")

    monkeypatch.setattr(tushare_gateway, "build_tushare_stock_adapter", lambda: None)
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: _Pro(),
    )

    with pytest.raises(tushare_gateway.TushareRelayAuthorizationError, match="HTTP 403"):
        tushare_gateway.TushareGateway().get_quote_snapshots(
            ["000001.SZ"], target_trade_date=date(2026, 9, 24)
        )


def test_history_routes_etf_index_and_stock_and_skips_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    valid = pd.DataFrame(
        [
            {
                "trade_date": "20240102",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "vol": 100,
                "amount": 200,
            },
            {
                "trade_date": "bad",
                "open": "bad",
                "high": 2,
                "low": 0.5,
                "close": 1.5,
            },
        ]
    )

    class _Pro:
        def fund_daily(self, **_kwargs: str) -> pd.DataFrame:
            calls.append("fund")
            return valid.copy()

        def index_daily(self, **_kwargs: str) -> pd.DataFrame:
            calls.append("index")
            return valid.copy()

        def daily(self, **_kwargs: str) -> pd.DataFrame:
            calls.append("daily")
            return valid.copy()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: _Pro(),
    )
    gateway = tushare_gateway.TushareGateway()
    assert len(gateway.get_historical_prices("510300.SH", "20240101", "20240131")) == 1
    assert len(gateway.get_historical_prices("000300.SH", "20240101", "20240131")) == 1
    assert len(gateway.get_historical_prices("000001.SZ", "20240101", "20240131")) == 1
    assert calls == ["fund", "index", "daily"]


def test_history_empty_and_exception_use_tencent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        tushare_gateway.TushareGateway,
        "_fallback_historical_prices",
        staticmethod(lambda asset, start, end: fallback.append((asset, start, end)) or []),
    )
    empty_pro = SimpleNamespace(
        fund_daily=lambda **_kwargs: pd.DataFrame(),
        index_daily=lambda **_kwargs: pd.DataFrame(),
        daily=lambda **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: empty_pro,
    )
    gateway = tushare_gateway.TushareGateway()
    assert gateway.get_historical_prices("510300.SH", "20240101", "20240131") == []

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
    assert len(fallback) == 2


def test_history_authorization_failure_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.data_center.infrastructure.tushare_client import TushareRelayAuthorizationError

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda **_kwargs: (_ for _ in ()).throw(TushareRelayAuthorizationError("HTTP 403")),
    )
    monkeypatch.setattr(
        tushare_gateway.TushareGateway,
        "_fallback_historical_prices",
        staticmethod(
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("authorization failures must not use fallback data")
            )
        ),
    )

    with pytest.raises(TushareRelayAuthorizationError, match="HTTP 403"):
        tushare_gateway.TushareGateway().get_historical_prices(
            "000001.SZ",
            "20240101",
            "20240131",
        )


def test_gateway_uses_its_configured_tushare_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def create_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(daily=lambda **_params: pd.DataFrame())

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        create_client,
    )
    gateway = tushare_gateway.TushareGateway(
        token="relay-token",
        http_url="https://relay.example.test/tushare/pro",
        request_mode="unified_relay",
        source_name="tushare-relay",
        provider_id=7,
        deployment_region="cn-east",
        dataset_key="equity.quote.snapshot",
    )

    gateway.get_historical_prices("000001.SZ", "20240101", "20240131")

    assert gateway.provider_name() == "tushare-relay"
    assert captured == {
        "token": "relay-token",
        "http_url": "https://relay.example.test/tushare/pro",
        "request_mode": "unified_relay",
        "provider_id": 7,
        "deployment_region": "cn-east",
        "dataset_key": "equity.quote.snapshot",
    }


def test_native_fallback_isolates_tencent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        lambda: (_ for _ in ()).throw(RuntimeError("tencent offline")),
    )
    assert (
        tushare_gateway.TushareGateway._fallback_historical_prices(
            "000001.SZ", "20240101", "20240131"
        )
        == []
    )
