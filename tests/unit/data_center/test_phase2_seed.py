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
def test_indicator_catalog_cutover_codes_exist_after_expansion():
    codes = set(
        IndicatorCatalogModel.objects.filter(
            code__in=[
                "CN_GDP_YOY",
                "CN_M2_YOY",
                "CN_DR007",
                "CN_PBOC_NET_INJECTION",
                "CN_FX_RESERVES",
            ]
        ).values_list("code", flat=True)
    )

    assert codes == {
        "CN_GDP_YOY",
        "CN_M2_YOY",
        "CN_DR007",
        "CN_PBOC_NET_INJECTION",
        "CN_FX_RESERVES",
    }


@pytest.mark.django_db
def test_indicator_catalog_seed_preserves_units_categories_and_period_types():
    gdp = IndicatorCatalogModel.objects.get(code="CN_GDP")
    pmi = IndicatorCatalogModel.objects.get(code="CN_PMI")
    cpi = IndicatorCatalogModel.objects.get(code="CN_CPI")
    ppi = IndicatorCatalogModel.objects.get(code="CN_PPI")
    m2 = IndicatorCatalogModel.objects.get(code="CN_M2")
    shibor = IndicatorCatalogModel.objects.get(code="CN_SHIBOR")

    assert gdp.default_unit == "亿元"
    assert gdp.default_period_type == "Q"
    assert gdp.category == "growth"

    assert pmi.default_unit == "指数"
    assert pmi.default_period_type == "M"
    assert pmi.category == "growth"

    assert cpi.default_unit == "指数"
    assert cpi.default_period_type == "M"
    assert cpi.category == "inflation"

    assert ppi.default_unit == "指数"
    assert ppi.default_period_type == "M"
    assert ppi.category == "inflation"

    assert m2.default_unit == "万亿元"
    assert m2.default_period_type == "M"
    assert m2.category == "money"

    assert shibor.default_unit == "%"
    assert shibor.default_period_type == "D"
    assert shibor.category == "money"
