"""Integrity tests for Fund ORM facts and reference data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.fund.infrastructure.models import (
    FundHoldingModel,
    FundInfoModel,
    FundManagerModel,
    FundNetValueModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
)


@pytest.mark.django_db
def test_fund_info_rejects_negative_or_nonfinite_scale() -> None:
    for index, scale in enumerate((Decimal("-1"), Decimal("NaN"))):
        with pytest.raises(ValidationError, match="基金规模"):
            FundInfoModel._default_manager.create(
                fund_code=f"00000{index + 1}",
                fund_name="测试基金",
                fund_type="股票型",
                fund_scale=scale,
            )

    assert not FundInfoModel._default_manager.exists()


@pytest.mark.django_db
def test_fund_manager_rejects_reversed_or_inconsistent_tenure() -> None:
    with pytest.raises(ValidationError):
        FundManagerModel._default_manager.create(
            fund_code="000001",
            manager_name="测试经理",
            tenure_start=date(2026, 7, 28),
            tenure_end=date(2026, 7, 27),
            is_current=True,
        )


@pytest.mark.django_db
def test_fund_nav_rejects_nonpositive_and_nonfinite_facts() -> None:
    with pytest.raises(ValidationError):
        FundNetValueModel._default_manager.create(
            fund_code="000001",
            nav_date=date(2026, 7, 28),
            unit_nav=Decimal("0"),
            accum_nav=Decimal("1"),
        )

    with pytest.raises(ValidationError, match="有限数"):
        FundNetValueModel._default_manager.create(
            fund_code="000001",
            nav_date=date(2026, 7, 28),
            unit_nav=Decimal("1"),
            accum_nav=Decimal("1"),
            daily_return=float("nan"),
        )


@pytest.mark.django_db
def test_fund_holding_database_constraints_block_bulk_bypass() -> None:
    holding = FundHoldingModel._default_manager.create(
        fund_code="000001",
        report_date=date(2026, 6, 30),
        stock_code="600519.SH",
        stock_name="贵州茅台",
        holding_amount=100,
        holding_value=Decimal("1000"),
        holding_ratio=10.0,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        FundHoldingModel._default_manager.filter(pk=holding.pk).update(holding_ratio=101.0)
    with pytest.raises(IntegrityError), transaction.atomic():
        FundHoldingModel._default_manager.filter(pk=holding.pk).update(holding_amount=-1)


@pytest.mark.django_db
def test_fund_sector_allocation_rejects_nonfinite_or_out_of_range_ratio() -> None:
    for ratio in (float("inf"), -0.1, 100.1):
        with pytest.raises(ValidationError):
            FundSectorAllocationModel._default_manager.create(
                fund_code="000001",
                report_date=date(2026, 6, 30),
                sector_name="电子",
                allocation_ratio=ratio,
            )


@pytest.mark.django_db
def test_fund_performance_rejects_invalid_window_and_metrics() -> None:
    with pytest.raises(ValidationError):
        FundPerformanceModel._default_manager.create(
            fund_code="000001",
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 27),
            total_return=1.0,
        )

    with pytest.raises(ValidationError, match="有限数"):
        FundPerformanceModel._default_manager.create(
            fund_code="000001",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 28),
            total_return=float("inf"),
        )


@pytest.mark.django_db
def test_fund_models_accept_valid_financial_facts() -> None:
    FundInfoModel._default_manager.create(
        fund_code="000001",
        fund_name="测试基金",
        fund_type="股票型",
        fund_scale=Decimal("1000000"),
    )
    FundNetValueModel._default_manager.create(
        fund_code="000001",
        nav_date=date(2026, 7, 28),
        unit_nav=Decimal("1.1234"),
        accum_nav=Decimal("2.3456"),
        daily_return=1.2,
    )

    assert FundInfoModel._default_manager.count() == 1
    assert FundNetValueModel._default_manager.count() == 1
