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
        source="tushare",
        published_at=date(2025, 1, 3),
    )

    adapter = MacroDataAdapter()

    assert adapter.get_indicator_value("CN_PMI") == pytest.approx(51.1)
