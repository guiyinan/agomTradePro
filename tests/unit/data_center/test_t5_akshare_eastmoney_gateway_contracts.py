"""Edge contracts for the AKShare/EastMoney market gateway."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from apps.data_center.infrastructure.gateways import akshare_eastmoney_gateway as gateway_module
from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
    AKShareEastMoneyGateway,
    _eastmoney_direct_network,
    _request_error_is_permission_denied,
    _safe_decimal,
    _safe_int,
    _to_akshare_code,
    _to_secid,
    _to_tushare_code,
    _to_tushare_code_from_eastmoney_row,
)
from apps.data_center.infrastructure.market_gateway_entities import (
    CapitalFlowSnapshot,
    HistoricalPriceBar,
    QuoteSnapshot,
    StockNewsItem,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability, ProviderHealth


def _quote(code: str = "600000.SH") -> QuoteSnapshot:
    return QuoteSnapshot(stock_code=code, price=Decimal("10.25"), source="test")


def _bar(code: str = "600000.SH") -> HistoricalPriceBar:
    return HistoricalPriceBar(
        asset_code=code,
        trade_date=date(2026, 7, 1),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        source="test",
    )


def test_code_and_numeric_helpers_cover_all_fallbacks() -> None:
    assert _to_akshare_code("600000") == "600000"
    assert _to_akshare_code("600000.SH") == "600000"
    assert _to_tushare_code(" 600000 ") == "600000.SH"
    assert _to_tushare_code("000001") == "000001.SZ"
    assert _to_tushare_code("300001") == "300001.SZ"
    assert _to_tushare_code("830001") == "830001.BJ"
    assert _to_tushare_code("430001") == "430001.BJ"
    assert _to_tushare_code("ABC123") == "ABC123.SZ"
    assert _to_tushare_code("000001.SZ") == "000001.SZ"
    assert _to_secid("830001.BJ") == "0.830001"
    assert _safe_decimal("12.5") == Decimal("12.5")
    assert _safe_decimal(None) is None
    assert _safe_decimal("") is None
    assert _safe_decimal("invalid") is None
    assert _safe_int("12.9") == 12
    assert _safe_int(None) is None
    assert _safe_int("") is None
    assert _safe_int("invalid") is None


def test_permission_detection_walks_causes_and_rejects_unrelated_errors() -> None:
    permission = PermissionError("blocked")
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = permission

    assert _request_error_is_permission_denied(wrapped) is True
    assert _request_error_is_permission_denied(ConnectionError("[WinError 10013] denied")) is True
    assert _request_error_is_permission_denied(RuntimeError("ordinary failure")) is False

    cyclic = RuntimeError("cycle")
    cyclic.__context__ = cyclic
    assert _request_error_is_permission_denied(cyclic) is False


def test_gateway_identity_support_and_period_contracts() -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)

    assert gateway.provider_name() == "eastmoney"
    assert gateway.supports(DataCapability.REALTIME_QUOTE) is True
    assert gateway.supports(ProviderHealth.UNKNOWN) is False  # type: ignore[arg-type]
    assert gateway._parse_period_days(" 10D ") == 10
    assert gateway._parse_period_days("badD") is None
    assert gateway._parse_period_days("month") is None
    assert gateway._is_index_asset("000300.SH") is True
    assert gateway._is_index_asset("600000.SH") is False
    assert gateway._is_index_asset("399001.SZ") is True
    assert gateway._is_index_asset("000300") is True
    assert gateway._is_index_asset("600000") is False


def test_quote_collection_keeps_direct_result_and_deduplicates_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = _quote("600000.SH")
    duplicate = _quote("600000.SH")
    fallback = _quote("000001.SZ")
    session = MagicMock()
    session.headers = {}
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)

    monkeypatch.setattr(gateway_module.requests, "Session", lambda: session)
    monkeypatch.setattr(
        gateway,
        "_fetch_quote_snapshot",
        lambda _session, code: direct if code == "600000.SH" else None,
    )
    monkeypatch.setattr(
        gateway,
        "_fetch_quote_snapshots_from_ulist",
        lambda _session, _codes: [duplicate, fallback],
    )

    snapshots = gateway.get_quote_snapshots(["600000.SH", "000001.SZ"])

    assert [snapshot.stock_code for snapshot in snapshots] == ["600000.SH", "000001.SZ"]
    assert session.trust_env is False


def test_capital_flow_filters_rows_and_ignores_unparseable_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame([{"day": 1}, {"day": 2}, {"day": 3}])
    akshare = SimpleNamespace(stock_individual_fund_flow=lambda **_kwargs: frame)
    parsed = CapitalFlowSnapshot(
        stock_code="600000.SH",
        trade_date=date(2026, 7, 1),
        main_net_inflow=1.0,
        main_net_ratio=2.0,
        source="test",
    )
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)

    monkeypatch.setattr(gateway_module, "get_akshare_module", lambda: akshare)
    monkeypatch.setattr(
        gateway_module,
        "parse_akshare_capital_flow_row",
        lambda row, _code: parsed if row["day"] == 3 else None,
    )

    assert gateway.get_capital_flows("600000.SH", period="2d") == [parsed]


@pytest.mark.parametrize("result", [None, pd.DataFrame()])
def test_capital_flow_handles_empty_provider_result(
    monkeypatch: pytest.MonkeyPatch,
    result: pd.DataFrame | None,
) -> None:
    akshare = SimpleNamespace(stock_individual_fund_flow=lambda **_kwargs: result)
    monkeypatch.setattr(gateway_module, "get_akshare_module", lambda: akshare)

    assert AKShareEastMoneyGateway(request_interval_sec=0).get_capital_flows("600000.SH") == []


def test_capital_flow_and_stock_news_isolate_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> object:
        raise RuntimeError("provider failed")

    monkeypatch.setattr(gateway_module, "get_akshare_module", fail)
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)

    assert gateway.get_capital_flows("600000.SH") == []
    assert gateway.get_stock_news("600000.SH") == []


def test_stock_news_delegates_to_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame([{"title": "news"}])
    item = StockNewsItem(stock_code="600000.SH", news_id="n1", title="News")
    akshare = SimpleNamespace(stock_news_em=lambda **_kwargs: frame)
    parser = MagicMock(return_value=[item])
    monkeypatch.setattr(gateway_module, "get_akshare_module", lambda: akshare)
    monkeypatch.setattr(gateway_module, "parse_akshare_news_rows", parser)

    result = AKShareEastMoneyGateway(request_interval_sec=0).get_stock_news(
        "600000.SH",
        limit=3,
    )

    assert result == [item]
    parser.assert_called_once_with(frame, "600000.SH", limit=3)


def test_market_news_handles_empty_rows_missing_summaries_and_default_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    empty_akshare = SimpleNamespace(stock_news_main_cx=lambda: pd.DataFrame())
    monkeypatch.setattr(gateway_module, "get_akshare_module", lambda: empty_akshare)
    assert gateway.get_market_news() == []

    frame = pd.DataFrame(
        [
            {"summary": "", "url": "", "tag": ""},
            {"summary": "市场向好", "url": "", "tag": ""},
        ]
    )
    monkeypatch.setattr(
        gateway_module,
        "get_akshare_module",
        lambda: SimpleNamespace(stock_news_main_cx=lambda: frame),
    )
    items = gateway.get_market_news(limit=2)

    assert len(items) == 1
    assert items[0].title == "市场动态: 市场向好"
    assert items[0].news_id == "cx-market-1"
    assert items[0].published_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError("blocked"), []),
        (RuntimeError("provider failed"), []),
    ],
)
def test_market_news_isolates_permission_and_generic_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: list[StockNewsItem],
) -> None:
    def fail() -> object:
        raise error

    monkeypatch.setattr(gateway_module, "get_akshare_module", fail)
    assert AKShareEastMoneyGateway(request_interval_sec=0).get_market_news() == expected


def test_technical_snapshot_handles_missing_and_available_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    monkeypatch.setattr(gateway, "get_quote_snapshots", lambda _codes: [])
    assert gateway.get_technical_snapshot("600000.SH") is None

    quote = QuoteSnapshot(
        stock_code="600000.SH",
        price=Decimal("10"),
        turnover_rate=1.2,
        volume_ratio=0.8,
    )
    monkeypatch.setattr(gateway, "get_quote_snapshots", lambda _codes: [quote])
    snapshot = gateway.get_technical_snapshot("600000.SH")

    assert snapshot is not None
    assert snapshot.close == Decimal("10")
    assert snapshot.turnover_rate == 1.2


@pytest.mark.parametrize(
    ("asset_code", "provider_method", "columns"),
    [
        (
            "510300.SH",
            "fund_etf_hist_em",
            {
                "日期": ["2026-07-01"],
                "开盘": [1],
                "最高": [2],
                "最低": [0.5],
                "收盘": [1.5],
            },
        ),
        (
            "000300.SH",
            "stock_zh_index_daily",
            {
                "date": ["2026-07-01"],
                "open": [1],
                "high": [2],
                "low": [0.5],
                "close": [1.5],
            },
        ),
        (
            "600000.SH",
            "stock_zh_a_hist",
            {
                "日期": ["2026-07-01"],
                "开盘": [1],
                "最高": [2],
                "最低": [0.5],
                "收盘": [1.5],
            },
        ),
    ],
)
def test_historical_prices_routes_each_asset_class(
    monkeypatch: pytest.MonkeyPatch,
    asset_code: str,
    provider_method: str,
    columns: dict[str, list[object]],
) -> None:
    provider = SimpleNamespace()
    setattr(provider, provider_method, lambda **_kwargs: pd.DataFrame(columns))
    monkeypatch.setattr(gateway_module, "get_akshare_module", lambda: provider)

    bars = AKShareEastMoneyGateway(request_interval_sec=0).get_historical_prices(
        asset_code,
        "20260701",
        "20260702",
    )

    assert len(bars) == 1
    assert bars[0].close == 1.5


def test_retry_contract_retries_transient_error_and_fast_fails_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    calls = iter([RuntimeError("temporary"), "ok"])

    def fetch() -> str:
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gateway_module.time, "sleep", lambda _seconds: None)
    assert (
        gateway._fetch_with_retries(
            fetch,
            asset_code="600000.SH",
            request_kind="history",
        )
        == "ok"
    )

    with pytest.raises(PermissionError):
        gateway._fetch_with_retries(
            lambda: (_ for _ in ()).throw(PermissionError("blocked")),
            asset_code="600000.SH",
            request_kind="history",
        )

    with pytest.raises(RuntimeError, match="always"):
        gateway._fetch_with_retries(
            lambda: (_ for _ in ()).throw(RuntimeError("always")),
            asset_code="600000.SH",
            request_kind="history",
            attempts=1,
        )


def test_history_circuit_opens_only_for_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway_module, "_history_circuit_open_until", 0.0)
    fallback = [object()]
    monkeypatch.setattr(
        AKShareEastMoneyGateway,
        "_fallback_historical_prices",
        staticmethod(lambda *_args: fallback),
    )

    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    monkeypatch.setattr(
        gateway,
        "_fetch_with_retries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad row")),
    )
    assert gateway.get_historical_prices("600000.SH", "20260701", "20260702") == fallback
    assert gateway_module._history_circuit_open_until == 0.0

    monkeypatch.setattr(
        gateway,
        "_fetch_with_retries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline")),
    )
    assert gateway.get_historical_prices("600000.SH", "20260701", "20260702") == fallback
    assert gateway_module._history_circuit_open_until > gateway_module.time.monotonic()


def test_historical_fallback_returns_empty_when_tencent_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTencent:
        def get_historical_prices(self, *_args: object) -> list[HistoricalPriceBar]:
            raise RuntimeError("fallback failed")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        FailingTencent,
    )
    assert AKShareEastMoneyGateway._fallback_historical_prices("X", "1", "2") == []


def test_open_history_circuit_bypasses_repeated_eastmoney_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gateway_module,
        "_history_circuit_open_until",
        gateway_module.time.monotonic() + 60,
    )
    monkeypatch.setattr(
        gateway_module,
        "get_akshare_module",
        lambda: (_ for _ in ()).throw(AssertionError("primary source must be bypassed")),
    )
    monkeypatch.setattr(
        AKShareEastMoneyGateway,
        "_fallback_historical_prices",
        staticmethod(lambda *_args: []),
    )

    assert (
        AKShareEastMoneyGateway(request_interval_sec=0).get_historical_prices(
            "600000.SH",
            "20260701",
            "20260731",
        )
        == []
    )


def test_bar_parsers_filter_dates_skip_bad_rows_and_require_date_columns() -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    assert gateway._parse_em_cn_bars(pd.DataFrame({"x": [1]}), "A", "test") == []
    assert (
        gateway._parse_en_bars(pd.DataFrame({"x": [1]}), "A", "20260701", "20260702", "test") == []
    )

    cn = pd.DataFrame(
        [
            {
                "日期": "2026-07-02",
                "开盘": "bad",
                "最高": 2,
                "最低": 1,
                "收盘": 1.5,
            },
            {
                "日期": "2026-07-01",
                "开盘": 1,
                "最高": 2,
                "最低": 0.5,
                "收盘": 1.5,
                "成交量": "12.9",
                "成交额": "100.5",
            },
        ]
    )
    cn_bars = gateway._parse_em_cn_bars(cn, "A", "test")
    assert len(cn_bars) == 1
    assert cn_bars[0].trade_date == date(2026, 7, 1)
    assert cn_bars[0].volume == 12
    assert cn_bars[0].amount == 100.5

    en = pd.DataFrame(
        [
            {"date": "2026-06-30", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            {"date": "2026-07-01", "open": "bad", "high": 2, "low": 0.5, "close": 1.5},
            {
                "date": "2026-07-02",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 25,
            },
        ]
    )
    en_bars = gateway._parse_en_bars(en, "A", "20260701", "20260702", "test")
    assert len(en_bars) == 1
    assert en_bars[0].trade_date == date(2026, 7, 2)
    assert en_bars[0].volume == 25


def test_quote_fetch_handles_request_failure_and_invalid_price() -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    failing_session = SimpleNamespace(
        get=lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.ConnectionError("offline"))
    )
    assert gateway._fetch_quote_snapshot(failing_session, "600000.SH") is None

    response = MagicMock()
    response.json.return_value = {"data": {"f43": 0}}
    session = SimpleNamespace(get=lambda *_args, **_kwargs: response)
    assert gateway._fetch_quote_snapshot(session, "600000.SH") is None


def test_ulist_helpers_cover_empty_invalid_unmapped_and_tencent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    assert gateway._fetch_quote_snapshots_from_ulist(MagicMock(), []) == []
    assert gateway._build_quote_snapshot_from_ulist_row({"f2": "-"}, requested_code=None) is None

    snapshot = gateway._build_quote_snapshot_from_ulist_row(
        {"f2": "8.5", "f12": "600000", "f13": "9"},
        requested_code=None,
    )
    assert snapshot is not None
    assert snapshot.stock_code == "600000.SH"
    assert _to_tushare_code_from_eastmoney_row({"f12": "600000", "f13": 1}) == "600000.SH"
    assert _to_tushare_code_from_eastmoney_row({"f12": "000001", "f13": 0}) == "000001.SZ"

    class FailingTencent:
        def get_quote_snapshots(self, _codes: list[str]) -> list[QuoteSnapshot]:
            raise RuntimeError("fallback failed")

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        FailingTencent,
    )
    assert gateway._fallback_quote_snapshots_from_tencent(["600000.SH"]) == []


def test_direct_network_context_restores_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {
        "HTTP_PROXY": "http://proxy",
        "NO_PROXY": "localhost",
        "no_proxy": "internal",
    }
    monkeypatch.setattr(gateway_module.os, "environ", environment)

    with _eastmoney_direct_network():
        assert "HTTP_PROXY" not in environment
        assert "eastmoney.com" in environment["NO_PROXY"]
        assert ".eastmoney.com" in environment["no_proxy"]

    assert environment["HTTP_PROXY"] == "http://proxy"
    assert environment["NO_PROXY"] == "localhost"
    assert environment["no_proxy"] == "internal"


def test_extract_market_news_datetime_uses_url_date_or_current_utc() -> None:
    parsed = AKShareEastMoneyGateway._extract_market_news_datetime(
        "https://example.com/2026-07-02/item"
    )
    fallback = AKShareEastMoneyGateway._extract_market_news_datetime("")

    assert parsed == datetime(2026, 7, 2, tzinfo=UTC)
    assert fallback.tzinfo is UTC
