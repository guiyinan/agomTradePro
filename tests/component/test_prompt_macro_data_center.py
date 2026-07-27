from datetime import date

import pytest

from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.prompt.infrastructure.adapters.macro_adapter import MacroDataAdapter


@pytest.mark.django_db
def test_prompt_macro_adapter_reads_data_center() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2025, 1, 1),
        value=51.1,
        unit="指数",
        source="akshare",
        published_at=date(2025, 1, 3),
    )

    adapter = MacroDataAdapter()

    assert adapter.get_indicator_value("CN_PMI") == pytest.approx(51.1)


@pytest.mark.django_db
def test_prompt_macro_tools_preserve_publication_cutoff_and_real_trend() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2025, 1, 1),
        value=50.0,
        unit="指数",
        source="akshare",
        published_at=date(2025, 1, 3),
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2025, 2, 1),
        value=52.0,
        unit="指数",
        source="akshare",
        published_at=date(2025, 3, 10),
    )
    adapter = MacroDataAdapter()

    assert adapter.get_indicator_value("CN_PMI", date(2025, 2, 28)) == pytest.approx(50.0)
    assert adapter.get_indicator_value("CN_PMI", date(2025, 3, 31)) == pytest.approx(52.0)
    assert adapter.calculate_trend("CN_PMI", "3m", date(2025, 3, 31)) == {
        "indicator": "CN_PMI",
        "period": "3m",
        "trend": "up",
        "change": 2.0,
        "change_pct": 4.0,
        "start_value": 50.0,
        "end_value": 52.0,
        "data_points": 2,
    }
