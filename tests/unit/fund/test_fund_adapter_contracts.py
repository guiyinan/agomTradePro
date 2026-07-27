"""Deterministic adapter contracts for fund data-source boundaries."""

import warnings
from types import SimpleNamespace
from typing import cast

import pandas as pd
import pytest
from django.core.cache.backends.base import CacheKeyWarning

from apps.fund.infrastructure.adapters.hybrid_fund_adapter import HybridFundAdapter
from apps.fund.infrastructure.adapters.tushare_fund_adapter import TushareFundAdapter
from shared.infrastructure.resilience import _cache_manager


class _FakeTusharePro:
    def fund_basic(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame(
            [{"ts_code": "510300.SH", "setup_date": "20120528", "list_date": "20120528"}]
        )

    def fund_nav(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame([{"nav_date": "20260723", "unit_nav": 1.2}])

    def fund_portfolio(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame([{"end_date": "20260630", "ts_code": "000001.SZ"}])

    def fund_daily(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame([{"trade_date": "20260723", "close": 4.2}])

    def fund_manager(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame([{"start_date": "20200101", "end_date": "20260723", "name": "manager"}])


def test_tushare_fund_adapter_normalizes_all_published_dates() -> None:
    adapter = TushareFundAdapter(token="token")
    adapter.pro = _FakeTusharePro()

    basic = adapter.fetch_fund_list()
    nav = adapter.fetch_fund_daily("510300.SH", "20260701", "20260724")
    portfolio = adapter.fetch_fund_portfolio("510300.SH", "20260101", "20260724")
    daily = adapter.fetch_fund_daily_basic("510300.SH", "20260701", "20260724")
    managers = adapter.fetch_fund_manager("510300.SH")
    holdings = adapter.fetch_fund_holdings_detail("510300.SH", "20260101", "20260724")

    assert str(basic.loc[0, "setup_date"].date()) == "2012-05-28"
    assert str(nav.loc[0, "trade_date"].date()) == "2026-07-23"
    assert str(portfolio.loc[0, "end_date"].date()) == "2026-06-30"
    assert str(daily.loc[0, "trade_date"].date()) == "2026-07-23"
    assert str(managers.loc[0, "start_date"].date()) == "2020-01-01"
    assert str(holdings.loc[0, "end_date"].date()) == "2026-06-30"


def test_tushare_fund_adapter_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.tushare_fund_adapter.get_secrets",
        lambda: SimpleNamespace(data_sources=SimpleNamespace(tushare_token="")),
    )

    with pytest.raises(ValueError, match="token"):
        TushareFundAdapter().fetch_fund_list()


def test_tushare_fund_adapter_normalizes_no_data_response() -> None:
    adapter = TushareFundAdapter(token="token")
    adapter.pro = SimpleNamespace(fund_nav=lambda **kwargs: None)

    result = adapter.fetch_fund_daily("510300.SH", "20260701", "20260724")

    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_tushare_fund_adapter_coerces_invalid_provider_dates() -> None:
    adapter = TushareFundAdapter(token="token")
    adapter.pro = SimpleNamespace(
        fund_portfolio=lambda **kwargs: pd.DataFrame(
            [{"end_date": "invalid-date", "ts_code": "000001.SZ"}]
        ),
        fund_daily=lambda **kwargs: pd.DataFrame([{"trade_date": "invalid-date", "close": 4.2}]),
    )

    portfolio = adapter.fetch_fund_portfolio("510300.SH", "20260101", "20260724")
    daily = adapter.fetch_fund_daily_basic("510300.SH", "20260701", "20260724")

    assert pd.isna(portfolio.loc[0, "end_date"])
    assert pd.isna(daily.loc[0, "trade_date"])


def test_hybrid_fund_adapter_uses_healthy_sources_and_exposes_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.is_healthy",
        lambda source: True,
    )
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.record_success",
        lambda source: calls.append(("success", source)),
    )
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.record_failure",
        lambda source, reason: calls.append(("failure", source)),
    )
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.get_health_status",
        lambda source: {"source": source, "healthy": True},
    )
    adapter = HybridFundAdapter(tushare_token="token")
    adapter._akshare_adapter = SimpleNamespace(
        fetch_fund_list_em=lambda: pd.DataFrame([{"代码": "510300"}]),
        fetch_fund_info_em=lambda code: pd.DataFrame([{"代码": code}]),
        fetch_fund_nav_em=lambda code: pd.DataFrame([{"代码": code, "净值": 1.2}]),
    )

    assert adapter.fetch_fund_list_em().iloc[0]["代码"] == "510300"
    assert adapter.fetch_fund_info_em("510300").iloc[0]["代码"] == "510300"
    assert adapter.fetch_fund_nav_em("510300").iloc[0]["净值"] == 1.2
    assert adapter.get_health_status()["akshare_fund"]["healthy"] is True
    assert ("success", "akshare_fund") in calls


def test_hybrid_fund_list_cache_key_is_backend_safe_and_cross_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fund-list cache scope excludes object repr and remains reusable across workers."""

    _cache_manager.clear()
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.is_healthy",
        lambda source: True,
    )
    monkeypatch.setattr(
        "apps.fund.infrastructure.adapters.hybrid_fund_adapter._health_manager.record_success",
        lambda source: None,
    )

    def fetch() -> pd.DataFrame:
        provider_calls.append(True)
        return pd.DataFrame([{"代码": "510300"}])

    first = HybridFundAdapter()
    second = HybridFundAdapter()
    first._akshare_adapter = SimpleNamespace(fetch_fund_list_em=fetch)
    second._akshare_adapter = SimpleNamespace(fetch_fund_list_em=fetch)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert first.fetch_fund_list_em().iloc[0]["代码"] == "510300"
        assert second.fetch_fund_list_em().iloc[0]["代码"] == "510300"

    assert provider_calls == [True]
    assert not [item for item in captured if issubclass(item.category, CacheKeyWarning)]


@pytest.mark.parametrize("fund_code", ["", "../secret", "51030", "510300 OF", True])
def test_hybrid_fund_detail_rejects_invalid_codes_before_provider(
    fund_code: object,
) -> None:
    """Malformed dynamic codes cannot enter provider calls or cache keys."""

    adapter = HybridFundAdapter()
    adapter._akshare_adapter = SimpleNamespace(
        fetch_fund_info_em=lambda code: pytest.fail("provider must not be called")
    )

    with pytest.raises(ValueError, match="fund_code"):
        adapter.fetch_fund_info_em(cast(str, fund_code))
