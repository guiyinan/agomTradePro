from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    PriceBarModel,
    ValuationFactModel,
)
from apps.equity.infrastructure.models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
def test_get_stock_context_rows_reads_financial_and_valuation_from_data_center():
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
        is_active=True,
    )
    StockDailyModel.objects.create(
        stock_code="000001.SZ",
        trade_date=date(2026, 5, 2),
        open=Decimal("12.10"),
        high=Decimal("12.50"),
        low=Decimal("12.00"),
        close=Decimal("12.34"),
        volume=123456,
        amount=Decimal("1234567.89"),
        adj_factor=1.0,
    )
    FinancialFactModel.objects.bulk_create(
        [
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="revenue",
                value=Decimal("1000000000.00"),
                unit="元",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="net_profit",
                value=Decimal("200000000.00"),
                unit="元",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="revenue_growth",
                value=Decimal("15.60"),
                unit="%",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="net_profit_growth",
                value=Decimal("18.20"),
                unit="%",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="total_assets",
                value=Decimal("10000000000.00"),
                unit="元",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="total_liabilities",
                value=Decimal("8000000000.00"),
                unit="元",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="equity",
                value=Decimal("2000000000.00"),
                unit="元",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="roe",
                value=Decimal("12.30"),
                unit="%",
                source="dc-test",
            ),
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2026, 3, 31),
                period_type="quarterly",
                metric_code="debt_ratio",
                value=Decimal("80.00"),
                unit="%",
                source="dc-test",
            ),
        ]
    )
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=date(2026, 5, 2),
        pe_ttm=Decimal("5.60"),
        pb=Decimal("0.72"),
        ps_ttm=Decimal("1.34"),
        market_cap=Decimal("250000000000.00"),
        float_market_cap=Decimal("240000000000.00"),
        dv_ratio=Decimal("4.50"),
        source="dc-test",
    )

    context = DjangoStockRepository().get_stock_context_rows(["000001.SZ"])

    assert context["000001.SZ"] == {
        "name": "平安银行",
        "sector": "银行",
        "market": "SZ",
        "trade_date": date(2026, 5, 2),
        "close": pytest.approx(12.34),
        "volume": pytest.approx(123456.0),
        "report_date": date(2026, 3, 31),
        "roe": pytest.approx(12.3),
        "debt_ratio": pytest.approx(80.0),
        "revenue_growth": pytest.approx(15.6),
        "profit_growth": pytest.approx(18.2),
        "valuation_trade_date": date(2026, 5, 2),
        "pe": pytest.approx(5.6),
        "pb": pytest.approx(0.72),
        "ps": pytest.approx(1.34),
        "dividend_yield": pytest.approx(4.5),
    }


@pytest.mark.django_db
def test_get_stock_context_rows_does_not_fallback_to_legacy_equity_fundamentals():
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
        is_active=True,
    )
    StockDailyModel.objects.create(
        stock_code="000001.SZ",
        trade_date=date(2026, 5, 2),
        open=Decimal("12.10"),
        high=Decimal("12.50"),
        low=Decimal("12.00"),
        close=Decimal("12.34"),
        volume=123456,
        amount=Decimal("1234567.89"),
        adj_factor=1.0,
    )
    FinancialDataModel.objects.create(
        stock_code="000001.SZ",
        report_date=date(2026, 3, 31),
        report_type="1Q",
        revenue=Decimal("1000000000.00"),
        net_profit=Decimal("200000000.00"),
        revenue_growth=15.6,
        net_profit_growth=18.2,
        total_assets=Decimal("10000000000.00"),
        total_liabilities=Decimal("8000000000.00"),
        equity=Decimal("2000000000.00"),
        roe=12.3,
        roa=1.1,
        debt_ratio=80.0,
    )
    ValuationModel.objects.create(
        stock_code="000001.SZ",
        trade_date=date(2026, 5, 2),
        pe=5.6,
        pb=0.72,
        ps=1.34,
        total_mv=Decimal("250000000000.00"),
        circ_mv=Decimal("240000000000.00"),
        dividend_yield=4.5,
        source_provider="legacy-test",
    )

    context = DjangoStockRepository().get_stock_context_rows(["000001.SZ"])

    assert context["000001.SZ"]["trade_date"] == date(2026, 5, 2)
    assert context["000001.SZ"]["close"] == pytest.approx(12.34)
    assert context["000001.SZ"]["volume"] == pytest.approx(123456.0)
    assert context["000001.SZ"]["report_date"] is None
    assert context["000001.SZ"]["roe"] is None
    assert context["000001.SZ"]["debt_ratio"] is None
    assert context["000001.SZ"]["revenue_growth"] is None
    assert context["000001.SZ"]["profit_growth"] is None
    assert context["000001.SZ"]["valuation_trade_date"] is None
    assert context["000001.SZ"]["pe"] is None
    assert context["000001.SZ"]["pb"] is None
    assert context["000001.SZ"]["ps"] is None
    assert context["000001.SZ"]["dividend_yield"] is None


@pytest.mark.django_db
def test_list_active_stock_codes_includes_price_covered_canonical_assets():
    AssetMasterModel.objects.create(
        code="600025.SH",
        name="华能水电",
        short_name="华能水电",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="600025.SH",
        bar_date=date(2026, 5, 6),
        open=Decimal("9.10"),
        high=Decimal("9.30"),
        low=Decimal("9.00"),
        close=Decimal("9.20"),
        volume=12345,
        amount=Decimal("1000000.00"),
        source="test",
    )

    codes = DjangoStockRepository().list_active_stock_codes()

    assert "600025.SH" in codes


@pytest.mark.django_db
def test_list_active_stock_codes_merges_local_and_price_covered_codes_without_duplicates():
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 5, 6),
        open=Decimal("12.10"),
        high=Decimal("12.50"),
        low=Decimal("12.00"),
        close=Decimal("12.34"),
        volume=123456,
        amount=Decimal("1234567.89"),
        source="test",
    )

    codes = DjangoStockRepository().list_active_stock_codes()

    assert codes.count("000001.SZ") == 1
