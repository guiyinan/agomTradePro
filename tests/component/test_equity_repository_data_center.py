from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.data_center.infrastructure.models import FinancialFactModel, ValuationFactModel
from apps.equity.domain.entities import FinancialData, ValuationMetrics
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
def test_get_financial_data_can_read_from_data_center_only():
    FinancialFactModel.objects.bulk_create(
        [
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="revenue",
                value=Decimal("1000000"),
                unit="元",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="net_profit",
                value=Decimal("200000"),
                unit="元",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="total_assets",
                value=Decimal("3000000"),
                unit="元",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="total_liabilities",
                value=Decimal("500000"),
                unit="元",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="equity",
                value=Decimal("2500000"),
                unit="元",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="roe",
                value=Decimal("18.5"),
                unit="%",
                source="tushare-main",
            ),
            FinancialFactModel(
                asset_code="600519.SH",
                period_end=date(2025, 12, 31),
                period_type="annual",
                metric_code="debt_ratio",
                value=Decimal("16.7"),
                unit="%",
                source="tushare-main",
            ),
        ]
    )

    repo = DjangoStockRepository()
    rows = repo.get_financial_data("600519.SH", limit=1)

    assert len(rows) == 1
    assert rows[0].revenue == Decimal("1000000.0000")
    assert rows[0].roe == 18.5
    assert rows[0].period_end == date(2025, 12, 31)
    assert rows[0].period_type == "annual"
    assert rows[0].source == "tushare-main"


@pytest.mark.django_db
def test_get_valuation_history_can_read_from_data_center_only():
    ValuationFactModel.objects.create(
        asset_code="600519.SH",
        val_date=date(2026, 3, 20),
        pe_ttm=Decimal("25.5"),
        pb=Decimal("8.2"),
        ps_ttm=Decimal("10.1"),
        market_cap=Decimal("2000000000000"),
        float_market_cap=Decimal("1800000000000"),
        dv_ratio=Decimal("1.2"),
        source="akshare-main",
    )

    repo = DjangoStockRepository()
    rows = repo.get_valuation_history("600519.SH", date(2026, 3, 1), date(2026, 3, 31))

    assert len(rows) == 1
    assert rows[0].pe == 25.5
    assert rows[0].source_provider == "akshare-main"


@pytest.mark.django_db
def test_latest_valuation_current_read_requires_publication(monkeypatch):
    """Current valuation reads reject non-empty rows from a blocked publication."""
    repo = DjangoStockRepository()
    repo._dc_valuation_repo.get_latest = lambda _code: (_ for _ in ()).throw(
        AssertionError("raw latest valuation must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "val_date": "2026-07-31",
                    "pe_ttm": 25.5,
                    "pb": 8.2,
                    "ps_ttm": 10.1,
                    "market_cap": 2_000_000_000_000,
                    "float_market_cap": 1_800_000_000_000,
                    "dv_ratio": 1.2,
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert repo._get_latest_valuation("600519.SH", published_only=True) is None


@pytest.mark.django_db
def test_latest_valuation_current_read_preserves_published_fact(monkeypatch):
    repo = DjangoStockRepository()
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "val_date": "2026-07-31",
                    "pe_ttm": 25.5,
                    "pb": 8.2,
                    "ps_ttm": 10.1,
                    "market_cap": 2_000_000_000_000,
                    "float_market_cap": 1_800_000_000_000,
                    "dv_ratio": 1.2,
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": False,
        },
    )

    valuation = repo._get_latest_valuation("600519.SH", published_only=True)

    assert valuation is not None
    assert valuation.trade_date == date(2026, 7, 31)
    assert valuation.pe == 25.5
    assert valuation.source_provider == "akshare-main"


@pytest.mark.django_db
def test_latest_financial_current_read_requires_publication(monkeypatch):
    repo = DjangoStockRepository()
    repo._dc_financial_repo.get_facts = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("raw latest financial facts must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_financial_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "period_end": "2025-12-31",
                    "period_type": "annual",
                    "metric_code": "roe",
                    "value": 18.5,
                    "unit": "%",
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert repo._get_latest_financial("600519.SH", published_only=True) is None


@pytest.mark.django_db
def test_latest_financial_current_read_preserves_published_facts(monkeypatch):
    values = {
        "revenue": (1_000_000.0, "元"),
        "net_profit": (200_000.0, "元"),
        "total_assets": (3_000_000.0, "元"),
        "total_liabilities": (500_000.0, "元"),
        "equity": (2_500_000.0, "元"),
        "roe": (18.5, "%"),
        "debt_ratio": (16.7, "%"),
    }
    fetched_at = datetime(2026, 7, 31, tzinfo=UTC).isoformat()
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_financial_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "period_end": "2025-12-31",
                    "period_type": "annual",
                    "metric_code": metric_code,
                    "value": value,
                    "unit": unit,
                    "source": "akshare-main",
                    "fetched_at": fetched_at,
                }
                for metric_code, (value, unit) in values.items()
            ],
            "must_not_use_for_decision": False,
        },
    )

    financial = DjangoStockRepository()._get_latest_financial("600519.SH", published_only=True)

    assert financial is not None
    assert financial.report_date == date(2025, 12, 31)
    assert financial.roe == 18.5
    assert financial.debt_ratio == 16.7
    assert financial.source == "akshare-main"
    assert financial.fetched_at == datetime(2026, 7, 31, tzinfo=UTC)


@pytest.mark.django_db
def test_latest_price_bar_current_read_requires_publication(monkeypatch):
    repo = DjangoStockRepository()
    repo._dc_price_bar_repo.get_latest = lambda _code: (_ for _ in ()).throw(
        AssertionError("raw latest price bar must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "timestamp": "2026-07-31",
                    "period": "1d",
                    "adjustment": "none",
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1690.0,
                    "close": 1710.0,
                    "volume": 123456.0,
                    "amount": 2_000_000_000.0,
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert repo._get_latest_price_bar("600519.SH", published_only=True) is None


@pytest.mark.django_db
def test_latest_price_bar_current_read_preserves_published_observation(monkeypatch):
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "timestamp": "2026-07-31",
                    "period": "1d",
                    "adjustment": "none",
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1690.0,
                    "close": 1710.0,
                    "volume": 123456.0,
                    "amount": 2_000_000_000.0,
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": False,
        },
    )

    bar = DjangoStockRepository()._get_latest_price_bar("600519.SH", published_only=True)

    assert bar is not None
    assert bar.bar_date == date(2026, 7, 31)
    assert bar.close == 1710.0
    assert bar.volume == 123456.0
    assert bar.fetched_at == datetime(2026, 7, 31, tzinfo=UTC)


@pytest.mark.django_db
def test_valuation_history_current_read_requires_publication(monkeypatch):
    repo = DjangoStockRepository()
    repo._dc_valuation_repo.get_series = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("raw valuation history must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "val_date": "2026-07-31",
                    "pe_ttm": 25.5,
                    "pb": 8.2,
                    "ps_ttm": 10.1,
                    "market_cap": 2_000_000_000_000,
                    "float_market_cap": 1_800_000_000_000,
                    "dv_ratio": 1.2,
                    "source": "akshare-main",
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert (
        repo.get_valuation_history(
            "600519.SH",
            date(2026, 7, 1),
            date(2026, 7, 31),
            published_only=True,
        )
        == []
    )


@pytest.mark.django_db
def test_valuation_history_current_read_preserves_published_observations(monkeypatch):
    fetched_at = datetime(2026, 7, 31, tzinfo=UTC).isoformat()
    monkeypatch.setattr(
        "apps.equity.infrastructure.fundamentals_repository.get_published_valuation_facts",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "asset_code": "600519.SH",
                    "val_date": val_date,
                    "pe_ttm": pe,
                    "pb": 8.2,
                    "ps_ttm": 10.1,
                    "market_cap": 2_000_000_000_000,
                    "float_market_cap": 1_800_000_000_000,
                    "dv_ratio": 1.2,
                    "source": "akshare-main",
                    "fetched_at": fetched_at,
                }
                for val_date, pe in (("2026-07-30", 24.5), ("2026-07-31", 25.5))
            ],
            "must_not_use_for_decision": False,
        },
    )

    rows = DjangoStockRepository().get_valuation_history(
        "600519.SH",
        date(2026, 7, 1),
        date(2026, 7, 31),
        published_only=True,
    )

    assert [row.trade_date for row in rows] == [date(2026, 7, 30), date(2026, 7, 31)]
    assert [row.pe for row in rows] == [24.5, 25.5]


@pytest.mark.django_db
def test_daily_prices_current_read_requires_publication(monkeypatch):
    repo = DjangoStockRepository()
    repo._dc_price_bar_repo.get_bars = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("raw daily prices must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.market_data_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "timestamp": "2026-07-31",
                    "close": 1710.0,
                    "fetched_at": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
                }
            ],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert (
        repo.get_daily_prices(
            "600519.SH",
            date(2026, 7, 1),
            date(2026, 7, 31),
            published_only=True,
        )
        == []
    )


@pytest.mark.django_db
def test_daily_prices_current_read_preserves_published_observations(monkeypatch):
    fetched_at = datetime(2026, 7, 31, tzinfo=UTC).isoformat()
    monkeypatch.setattr(
        "apps.equity.infrastructure.market_data_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {"timestamp": "2026-07-30", "close": 1700.0, "fetched_at": fetched_at},
                {"timestamp": "2026-07-31", "close": 1710.0, "fetched_at": fetched_at},
            ],
            "must_not_use_for_decision": False,
        },
    )

    rows = DjangoStockRepository().get_daily_prices(
        "600519.SH",
        date(2026, 7, 1),
        date(2026, 7, 31),
        published_only=True,
    )

    assert rows == [
        (date(2026, 7, 30), Decimal("1700.0")),
        (date(2026, 7, 31), Decimal("1710.0")),
    ]


@pytest.mark.django_db
def test_technical_bars_current_read_requires_publication(monkeypatch):
    repo = DjangoStockRepository()
    repo._dc_price_bar_repo.get_bars = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("raw technical bars must not be read")
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.market_data_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_stale",
        },
    )

    assert (
        repo.get_technical_bars(
            "600519.SH",
            date(2026, 7, 1),
            date(2026, 7, 31),
            published_only=True,
        )
        == []
    )


@pytest.mark.django_db
def test_technical_bars_current_read_preserves_published_ohlcv(monkeypatch):
    fetched_at = datetime(2026, 7, 31, tzinfo=UTC).isoformat()
    monkeypatch.setattr(
        "apps.equity.infrastructure.market_data_repository.get_published_price_bar_series",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "timestamp": "2026-07-30",
                    "open": 1690.0,
                    "high": 1710.0,
                    "low": 1680.0,
                    "close": 1700.0,
                    "volume": 1000,
                    "amount": 1_700_000,
                    "fetched_at": fetched_at,
                },
                {
                    "timestamp": "2026-07-31",
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1695.0,
                    "close": 1710.0,
                    "volume": 1200,
                    "amount": 2_052_000,
                    "fetched_at": fetched_at,
                },
            ],
            "must_not_use_for_decision": False,
        },
    )

    rows = DjangoStockRepository().get_technical_bars(
        "600519.SH",
        date(2026, 7, 1),
        date(2026, 7, 31),
        published_only=True,
    )

    assert [row.trade_date for row in rows] == [date(2026, 7, 30), date(2026, 7, 31)]
    assert [row.close for row in rows] == [Decimal("1700.0"), Decimal("1710.0")]
    assert rows[-1].volume == 1200


@pytest.mark.django_db
def test_save_methods_mirror_equity_data_to_data_center():
    repo = DjangoStockRepository()
    repo.save_financial_data(
        FinancialData(
            stock_code="600519.SH",
            report_date=date(2025, 12, 31),
            revenue=Decimal("1000000"),
            net_profit=Decimal("200000"),
            revenue_growth=12.0,
            net_profit_growth=10.0,
            total_assets=Decimal("3000000"),
            total_liabilities=Decimal("500000"),
            equity=Decimal("2500000"),
            roe=18.5,
            roa=12.2,
            debt_ratio=16.7,
        )
    )
    repo.save_valuation(
        ValuationMetrics(
            stock_code="600519.SH",
            trade_date=date(2026, 3, 20),
            pe=25.5,
            pb=8.2,
            ps=10.1,
            total_mv=Decimal("2000000000000"),
            circ_mv=Decimal("1800000000000"),
            dividend_yield=1.2,
            source_provider="legacy-test",
        )
    )

    assert FinancialFactModel.objects.filter(asset_code="600519.SH").count() >= 7
    assert ValuationFactModel.objects.filter(asset_code="600519.SH").count() == 1
