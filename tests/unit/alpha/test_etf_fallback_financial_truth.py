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
    remote.assert_not_called()


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


def test_etf_fallback_keeps_holdings_observable_but_unqualified_for_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ETFFallbackProvider()
    trade_date = date(2026, 1, 5)
    monkeypatch.setattr(provider, "supports", lambda universe_id, pool_scope=None: True)
    monkeypatch.setattr(
        provider,
        "_resolve_etf_info",
        lambda universe_id: {
            "etf_code": "510300.SH",
            "etf_name": "CSI 300 ETF",
            "report_date": "2025-12-31",
        },
    )
    monkeypatch.setattr(
        provider,
        "_get_etf_constituents",
        lambda etf_code, intended_trade_date, top_n: (
            [("600519.SH", 4.5)],
            None,
            {"holdings_source": "database", "report_date": "2025Q4"},
        ),
    )

    result = provider.get_stock_scores("csi300", trade_date)

    assert result.success is True
    assert result.status == "degraded"
    assert result.staleness_days is None
    assert result.metadata["report_date"] == "2025Q4"
    assert result.metadata["holdings_source"] == "database"
    assert result.metadata["source_observed_at"] is None
    assert result.metadata["source_available_at"] is None
    assert result.metadata["freshness_status"] == "unknown"
    assert result.metadata["must_not_use_for_decision"] is True
    assert result.metadata["must_not_execute"] is True
    assert result.metadata["blocked_reason"] == "alpha_etf_holdings_unqualified"
    assert result.metadata["factor_basis"] == "etf_holdings_observation"
    score = result.scores[0]
    assert score.source == "etf"
    assert score.score == pytest.approx(0.045)
    assert score.factors == {"holding_ratio_pct": 4.5}
    assert score.asof_date is None
    assert score.intended_trade_date == trade_date


def test_public_etf_score_read_does_not_fetch_or_write_remote_holdings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ETFFallbackProvider()
    trade_date = date(2026, 1, 5)
    monkeypatch.setattr(provider, "supports", lambda universe_id, pool_scope=None: True)
    monkeypatch.setattr(
        provider,
        "_resolve_etf_info",
        lambda universe_id: {
            "etf_code": "510300.SH",
            "etf_name": "CSI 300 ETF",
            "report_date": None,
        },
    )
    holding_manager = FundHoldingModel._default_manager
    base_queryset = Mock()
    empty_filtered_queryset = Mock()
    base_queryset.filter.return_value = empty_filtered_queryset
    empty_filtered_queryset.order_by.return_value.values_list.return_value.first.return_value = None
    monkeypatch.setattr(holding_manager, "get_queryset", Mock(return_value=base_queryset))
    remote_read = Mock(
        return_value=(
            [("600519.SH", 4.5)],
            None,
            {"holdings_source": "eastmoney", "report_date": "2025Q4"},
        )
    )
    monkeypatch.setattr(provider, "_get_remote_etf_constituents", remote_read)

    result = provider.get_stock_scores("csi300", trade_date)

    assert result.success is False
    remote_read.assert_not_called()
    base_queryset.update_or_create.assert_not_called()


@override_settings(ALPHA_UNIVERSE_ETF_MAP={})
def test_etf_fallback_has_no_hardcoded_universe_map() -> None:
    provider = ETFFallbackProvider()

    assert provider.get_supported_universes() == []
