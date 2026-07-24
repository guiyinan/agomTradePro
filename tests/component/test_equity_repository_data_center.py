from __future__ import annotations

from datetime import date
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
