from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.equity.infrastructure.models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
def test_get_stock_context_rows_includes_latest_financial_and_valuation_metrics():
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
        source_provider="test",
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
