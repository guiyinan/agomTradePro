from datetime import date, timedelta

import pytest

from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.regime.application.use_cases import (
    CalculateRegimeRequest,
    CalculateRegimeUseCase,
)
from apps.regime.infrastructure.macro_data_provider import (
    DjangoMacroDataProvider,
    MacroRepositoryAdapter,
)


def _month_start(base: date, offset: int) -> date:
    month_index = (base.month - 1) + offset
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    return date(year, month, 1)


@pytest.mark.django_db
def test_django_macro_data_provider_reads_data_center_facts() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "name_en": "PMI",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2025, 1, 1),
        value=50.8,
        unit="指数",
        source="tushare",
        published_at=date(2025, 1, 3),
    )

    provider = DjangoMacroDataProvider()

    result = provider.get_indicator_value("CN_PMI")

    assert result is not None
    assert result.value == 50.8
    assert result.observed_at == date(2025, 1, 1)
    assert result.unit == "指数"


@pytest.mark.django_db
def test_macro_repository_adapter_and_regime_use_case_run_on_data_center() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "name_en": "PMI",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_CPI_NATIONAL_YOY",
        defaults={
            "name_cn": "全国CPI同比",
            "name_en": "CPI YoY",
            "default_unit": "%",
            "default_period_type": "M",
            "category": "inflation",
        },
    )

    base = date(2023, 1, 1)
    for offset in range(30):
        reporting_period = _month_start(base, offset)
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=reporting_period,
            value=49.0 + (offset * 0.12),
            unit="指数",
            source="tushare",
            published_at=reporting_period + timedelta(days=2),
        )
        MacroFactModel.objects.create(
            indicator_code="CN_CPI_NATIONAL_YOY",
            reporting_period=reporting_period,
            value=0.012 + (offset * 0.0004),
            unit="%",
            source="tushare",
            published_at=reporting_period + timedelta(days=10),
        )

    repository = MacroRepositoryAdapter()
    as_of_date = _month_start(base, 29)

    inflation_series = repository.get_inflation_series(
        indicator_code="CPI",
        end_date=as_of_date,
        source="tushare",
    )
    assert len(inflation_series) == 30
    assert inflation_series[0] == pytest.approx(1.2)

    response = CalculateRegimeUseCase(repository=repository).execute(
        CalculateRegimeRequest(
            as_of_date=as_of_date,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source="tushare",
        )
    )

    assert response.success
    assert response.snapshot is not None
    assert response.raw_data is not None
    assert len(response.raw_data["growth"]) == 30
    assert len(response.raw_data["inflation"]) == 30


@pytest.mark.django_db
def test_data_center_macro_repository_does_not_fallback_to_legacy_macro_table() -> None:
    repository = MacroRepositoryAdapter()

    observation = repository.get_latest_observation("CN_PMI")

    assert observation is None
