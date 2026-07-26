from datetime import date
from unittest.mock import Mock

import pytest
from django.test import override_settings

from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel


@pytest.mark.django_db
@override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
def test_etf_fallback_excludes_holdings_not_observed_by_trade_date(monkeypatch) -> None:
    FundInfoModel._default_manager.create(
        fund_code="510300",
        fund_name="沪深300ETF",
        fund_type="指数型",
        is_active=True,
    )
    FundHoldingModel._default_manager.create(
        fund_code="510300",
        report_date=date(2025, 12, 31),
        stock_code="600519.SH",
        stock_name="贵州茅台",
        holding_ratio=4.5,
    )
    provider = ETFFallbackProvider()
    remote = Mock(
        return_value=(
            [],
            "Historical ETF holdings are unavailable from a point-in-time source",
            {},
        )
    )
    monkeypatch.setattr(provider, "_get_remote_etf_constituents", remote)

    result = provider.get_stock_scores("csi300", date(2025, 12, 31))

    assert result.success is False
    remote.assert_called_once()


@override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
def test_etf_fallback_rejects_historical_remote_backfill(monkeypatch) -> None:
    provider = ETFFallbackProvider()
    remote_source = Mock()
    monkeypatch.setattr(
        "apps.alpha.infrastructure.adapters.etf_adapter.get_akshare_module",
        remote_source,
    )

    constituents, error, metadata = provider._get_remote_etf_constituents(
        "510300.SH",
        date(2020, 12, 31),
        10,
    )

    assert constituents == []
    assert error == "Historical ETF holdings are unavailable from a point-in-time source"
    assert metadata == {}
    remote_source.assert_not_called()


def test_etf_fallback_normalizes_percent_scores_and_drops_invalid_ratios() -> None:
    provider = ETFFallbackProvider()

    constituents, error, metadata = provider._normalize_constituents_payload(
        (
            [
                ("600519", 5.89),
                ("000001", float("nan")),
                ("000002", -1),
                ("000003", 101),
                ("", 3),
            ],
            None,
            {"holdings_source": "database", "ignored": None},
        )
    )

    assert constituents == [("600519.SH", 5.89)]
    assert error is None
    assert metadata == {"holdings_source": "database"}


@override_settings(ALPHA_UNIVERSE_ETF_MAP={})
def test_etf_fallback_has_no_hardcoded_universe_map() -> None:
    provider = ETFFallbackProvider()

    assert provider.get_supported_universes() == []
