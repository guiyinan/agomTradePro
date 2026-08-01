"""Bulk persistence contracts for production core-data rebuilds."""

from datetime import date

import pytest

from apps.data_center.domain.entities import FinancialFact, PriceBar, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure.fundamental_fact_repositories import (
    FinancialFactRepository,
    ValuationFactRepository,
)
from apps.data_center.infrastructure.market_data_repositories import PriceBarRepository
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
    PriceBarModel,
    ValuationFactModel,
)

pytestmark = pytest.mark.django_db


def test_price_bulk_upsert_updates_conflicts_in_one_statement(
    django_assert_num_queries: object,
) -> None:
    repository = PriceBarRepository()
    first = PriceBar(
        asset_code="000001.SZ",
        bar_date=date(2026, 7, 31),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        source="akshare",
    )
    revised = PriceBar(
        asset_code=first.asset_code,
        bar_date=first.bar_date,
        open=10.0,
        high=12.0,
        low=9.0,
        close=11.5,
        source=first.source,
    )

    with django_assert_num_queries(1):  # type: ignore[operator]
        assert repository.bulk_upsert([first]) == 1
    with django_assert_num_queries(1):  # type: ignore[operator]
        assert repository.bulk_upsert([revised]) == 1

    assert PriceBarModel._default_manager.get().close == 11.5


def test_financial_and_valuation_bulk_upserts_update_natural_keys() -> None:
    financial_repository = FinancialFactRepository()
    valuation_repository = ValuationFactRepository()
    financial = FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="revenue",
        value=100.0,
        unit="元",
        source="akshare",
    )
    valuation = ValuationFact(
        asset_code="000001.SZ",
        val_date=date(2026, 7, 31),
        pe_ttm=10.0,
        pb=1.0,
        source="akshare",
    )

    assert financial_repository.bulk_upsert([financial]) == 1
    assert valuation_repository.bulk_upsert([valuation]) == 1
    assert (
        financial_repository.bulk_upsert(
            [
                FinancialFact(
                    **{
                        **financial.__dict__,
                        "value": 120.0,
                    }
                )
            ]
        )
        == 1
    )
    assert (
        valuation_repository.bulk_upsert(
            [
                ValuationFact(
                    **{
                        **valuation.__dict__,
                        "pe_ttm": 12.0,
                    }
                )
            ]
        )
        == 1
    )

    assert FinancialFactModel._default_manager.get().value == 120.0
    assert ValuationFactModel._default_manager.get().pe_ttm == 12.0
    assert FinancialFactModel._default_manager.count() == 1
    assert ValuationFactModel._default_manager.count() == 1
