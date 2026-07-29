"""T3A contracts for shared unified-provider adapter behavior."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
import requests

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability, FinancialPeriodType
from apps.data_center.infrastructure import _provider_adapter_base as adapter_base


def _config(source_type: str = "akshare") -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="fixture",
        source_type=source_type,
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_macro_fetch_converts_only_provider_unavailable_errors() -> None:
    unavailable_type = type("DataSourceUnavailableError", (Exception,), {})
    adapter = SimpleNamespace(
        fetch=lambda *_args: (_ for _ in ()).throw(unavailable_type("offline"))
    )
    with pytest.raises(ConnectionError, match="macro_source_unavailable"):
        adapter_base._fetch_macro_points(adapter, "CN_CPI", date(2024, 1, 1), date(2024, 2, 1))

    adapter.fetch = lambda *_args: [1]
    assert adapter_base._fetch_macro_points(
        adapter, "CN_CPI", date(2024, 1, 1), date(2024, 2, 1)
    ) == [1]


def test_datetime_period_and_date_helpers_cover_all_formats() -> None:
    naive = datetime(2024, 1, 1)
    assert adapter_base._ensure_aware(None).tzinfo is not None
    assert adapter_base._ensure_aware(naive).tzinfo is UTC
    assert adapter_base._ensure_aware(naive.replace(tzinfo=UTC)).tzinfo is UTC

    expected = {
        "annual": FinancialPeriodType.ANNUAL,
        "2q": FinancialPeriodType.SEMI_ANNUAL,
        "3q": FinancialPeriodType.QUARTERLY,
        "ttm": FinancialPeriodType.TTM,
        "unknown": FinancialPeriodType.QUARTERLY,
    }
    assert {value: adapter_base._to_period_type(value) for value in expected} == expected
    assert (
        adapter_base._period_type_from_period_end(date(2024, 12, 31)) is FinancialPeriodType.ANNUAL
    )
    assert (
        adapter_base._period_type_from_period_end(date(2024, 6, 30))
        is FinancialPeriodType.SEMI_ANNUAL
    )
    assert (
        adapter_base._period_type_from_period_end(date(2024, 3, 31))
        is FinancialPeriodType.QUARTERLY
    )

    assert adapter_base._safe_date(None) is None
    assert adapter_base._safe_date(naive) == date(2024, 1, 1)
    assert adapter_base._safe_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert adapter_base._safe_date("2024-01-03") == date(2024, 1, 3)
    assert adapter_base._safe_date("20240104") == date(2024, 1, 4)
    assert adapter_base._safe_date("bad") is None
    assert adapter_base._safe_month_end_date("2024-02") == date(2024, 2, 29)
    assert adapter_base._safe_month_end_date("bad") is None


def test_generic_helpers_and_capability_defaults() -> None:
    assert adapter_base._first_present({"b": 2}, "a", "b") == 2
    assert adapter_base._first_present({}, "a") is None
    assert adapter_base._valuation_period(date(2024, 1, 1), date(2024, 2, 1)) == "近一年"
    assert adapter_base._valuation_period(date(2020, 1, 1), date(2024, 1, 1)) == "近五年"
    assert adapter_base._valuation_period(date(2010, 1, 1), date(2024, 1, 1)) == "全部"
    assert adapter_base._score_market_news_sentiment("") == 0
    assert adapter_base._score_market_news_sentiment("上涨 回升 突破 新高") == 1
    assert adapter_base._score_market_news_sentiment("下跌 风险 承压 新低") == -1

    adapter = adapter_base.BaseUnifiedProviderAdapter(_config())
    assert adapter.provider_name() == "fixture"
    assert adapter.provider_source() == "akshare"
    assert adapter.supports(DataCapability.MACRO)
    assert adapter._provider_extra()["provider_name"] == "fixture"
    assert adapter.fetch_macro_series("CN_CPI", date.today(), date.today()) == []
    assert adapter.fetch_price_history("000001.SZ", date.today(), date.today()) == []
    assert adapter.fetch_quote_snapshots(["000001.SZ"]) == []
    assert adapter.fetch_fund_nav("510300.SH", date.today(), date.today()) == []
    assert adapter.fetch_financials("000001.SZ") == []
    assert adapter.fetch_valuations("000001.SZ", date.today(), date.today()) == []
    assert adapter.fetch_sector_memberships() == []
    assert adapter.fetch_news("000001.SZ") == []
    assert adapter.fetch_capital_flows("000001.SZ") == []


def test_tencent_turnover_aggregates_valid_index_amounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def get_historical_prices(self, asset_code: str, _start: str, _end: str) -> list[object]:
            amount = 100 if asset_code.endswith(".SH") else 200
            return [
                SimpleNamespace(
                    trade_date=date(2024, 1, 2),
                    amount=amount,
                ),
                SimpleNamespace(
                    trade_date=date(2023, 12, 31),
                    amount=999,
                ),
                SimpleNamespace(
                    trade_date=date(2024, 1, 3),
                    amount=None,
                ),
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway",
        _Gateway,
    )
    result = adapter_base.BaseUnifiedProviderAdapter(_config())._fetch_market_turnover_from_tencent(
        date(2024, 1, 1), date(2024, 1, 31)
    )
    assert result[0].value == 300
    assert result[0].extra["fallback_provider"] == "tencent"


def test_eastmoney_turnover_requires_both_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"f48": 100}}

    class _Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> _Session:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response()

    monkeypatch.setattr(adapter_base.requests, "Session", _Session)
    adapter = adapter_base.BaseUnifiedProviderAdapter(_config())
    result = adapter._fetch_market_turnover_from_eastmoney_quote(date(2024, 1, 2))
    assert result[0].value == 200

    class _FailingSession(_Session):
        calls = 0

        def get(self, *_args: object, **_kwargs: object) -> _Response:
            self.calls += 1
            if self.calls > 1:
                raise requests.ConnectionError("offline")
            return _Response()

    monkeypatch.setattr(adapter_base.requests, "Session", _FailingSession)
    monkeypatch.setattr(adapter_base, "sleep", lambda _seconds: None)
    assert adapter._fetch_market_turnover_from_eastmoney_quote(date(2024, 1, 2)) == []
