"""Database-backed checks for Phase 2 indicator catalog seed data."""

import pytest

from apps.data_center.infrastructure.models import IndicatorCatalogModel


@pytest.mark.django_db
def test_indicator_catalog_seed_contains_core_phase2_codes():
    codes = set(
        IndicatorCatalogModel.objects.filter(
            code__in=["CN_GDP", "CN_PMI", "CN_CPI", "CN_M2", "CN_SHIBOR"]
        ).values_list("code", flat=True)
    )

    assert codes == {"CN_GDP", "CN_PMI", "CN_CPI", "CN_M2", "CN_SHIBOR"}


@pytest.mark.django_db
def test_indicator_catalog_seed_preserves_units_categories_and_period_types():
    gdp = IndicatorCatalogModel.objects.get(code="CN_GDP")
    shibor = IndicatorCatalogModel.objects.get(code="CN_SHIBOR")

    assert gdp.default_unit == "亿元"
    assert gdp.default_period_type == "Q"
    assert gdp.category == "growth"

    assert shibor.default_unit == "%"
    assert shibor.default_period_type == "D"
    assert shibor.category == "money"
