"""T3A AKShare unified-provider conversion contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import _provider_adapter_akshare
from apps.data_center.infrastructure._provider_adapter_akshare import (
    AkshareUnifiedProviderAdapter,
)

START = date(2024, 1, 1)
END = date(2024, 12, 31)


def _adapter() -> AkshareUnifiedProviderAdapter:
    return AkshareUnifiedProviderAdapter(
        ProviderConfig(
            id=1,
            name="AKShare Fixture",
            source_type="akshare",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )
    )


def test_general_macro_points_are_normalized_and_missing_dates_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    points = [
        SimpleNamespace(
            observed_at=START,
            value=3.2,
            unit="%",
            original_unit="percent",
            published_at=START,
        ),
        SimpleNamespace(observed_at=None, value=1),
    ]
    monkeypatch.setattr(
        _provider_adapter_akshare,
        "_fetch_macro_points",
        lambda *_args: points,
    )

    result = _adapter().fetch_macro_series("CN_CPI", START, END)

    assert len(result) == 1
    assert result[0].extra["original_unit"] == "percent"
    assert _adapter().fetch_macro_series("CN_A_ETF_SIZE_FLOW", START, END) == []


def test_margin_balance_combines_markets_and_skips_bad_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SimpleNamespace(
        macro_china_market_margin_sh=lambda: pd.DataFrame(
            [
                {"日期": "2024-01-02", "融资余额": 100},
                {"日期": "bad", "融资余额": 999},
            ]
        ),
        macro_china_market_margin_sz=lambda: pd.DataFrame(
            [
                {"date": "2024-01-02", "融资余额": 200},
                {"date": "2023-01-02", "融资余额": 300},
                {"date": "2024-01-03", "融资余额": None},
            ]
        ),
    )
    monkeypatch.setattr(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        lambda: source,
    )

    result = _adapter().fetch_macro_series("CN_A_MARGIN_BALANCE", START, END)

    assert len(result) == 1
    assert result[0].value == 300


def test_price_quote_and_stock_news_gateway_rows_are_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway:
        def get_historical_prices(self, **_kwargs: object) -> list[object]:
            return [
                SimpleNamespace(
                    trade_date=START,
                    open=1,
                    high=2,
                    low=0.5,
                    close=1.5,
                    volume=100,
                    amount=200,
                )
            ]

        def get_quote_snapshots(self, _codes: list[str]) -> list[object]:
            return [
                SimpleNamespace(
                    stock_code="000001.SZ",
                    observed_at=datetime(2024, 1, 2, tzinfo=UTC),
                    fetched_at=datetime(2024, 1, 2, tzinfo=UTC),
                    price=Decimal("10.5"),
                    open=10,
                    high=11,
                    low=9,
                    pre_close=10.2,
                    volume=1000,
                    amount=2000,
                    source="eastmoney",
                )
            ]

        def get_stock_news(self, _code: str, limit: int) -> list[object]:
            assert limit == 1
            return [
                SimpleNamespace(
                    stock_code="000001.SZ",
                    title="News",
                    content="Content",
                    published_at=datetime(2024, 1, 2),
                    url="https://example.test/news",
                    news_id="n1",
                )
            ]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway."
        "AKShareEastMoneyGateway",
        _Gateway,
    )
    adapter = _adapter()

    prices = adapter.fetch_price_history("000001", START, END)
    quotes = adapter.fetch_quote_snapshots(["000001.SZ"])
    news = adapter.fetch_news("000001.SZ", limit=1)

    assert prices[0].asset_code == "000001.SZ"
    assert quotes[0].current_price == 10.5
    assert quotes[0].source == "eastmoney"
    assert quotes[0].extra["actual_source"] == "eastmoney"
    assert news[0].published_at.tzinfo is UTC


def test_fund_nav_filters_missing_and_out_of_range_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {"nav_date": pd.Timestamp("2023-01-01"), "unit_nav": 2},
            {
                "nav_date": pd.Timestamp("2024-01-02"),
                "unit_nav": 3,
                "累计净值": 4,
            },
        ]
    )
    monkeypatch.setattr(
        _provider_adapter_akshare,
        "get_akshare_module",
        lambda: SimpleNamespace(
            fund_open_fund_info_em=lambda **_kwargs: frame,
        ),
    )

    result = _adapter().fetch_fund_nav("510300.SH", START, END)

    assert len(result) == 1
    assert result[0].nav == 3


def test_sector_membership_fails_closed_without_stable_akshare_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _adapter().fetch_sector_memberships(sector_code="BK001", effective_date=START)
    missing = _adapter().fetch_sector_memberships(sector_code="UNKNOWN")

    assert result == []
    assert missing == []
