"""T3A Tushare gateway conversion, routing, and fallback contracts."""

from __future__ import annotations

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

    monkeypatch.setattr(
        tushare_gateway,
        "build_tushare_stock_adapter",
        lambda: (_ for _ in ()).throw(RuntimeError("batch failure")),
    )
    assert tushare_gateway.TushareGateway().get_quote_snapshots(["000001.SZ"]) == []


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
        lambda: _Pro(),
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
        lambda: empty_pro,
    )
    gateway = tushare_gateway.TushareGateway()
    assert gateway.get_historical_prices("510300.SH", "20240101", "20240131") == []

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
    assert len(fallback) == 2


def test_history_authorization_failure_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.data_center.infrastructure.tushare_client import TushareRelayAuthorizationError

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.create_tushare_pro_client",
        lambda: (_ for _ in ()).throw(TushareRelayAuthorizationError("HTTP 403")),
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
