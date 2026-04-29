from io import StringIO

import pytest
from django.core.management import call_command

from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
)


@pytest.mark.django_db
def test_normalize_macro_fact_units_repairs_legacy_currency_row():
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_NEW_CREDIT",
        defaults={
            "name_cn": "新增信贷",
            "default_unit": "亿元",
            "default_period_type": "M",
            "category": "financial",
            "is_active": True,
        },
    )
    rule, _ = IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code="CN_NEW_CREDIT",
        source_type="",
        dimension_key="currency",
        original_unit="亿元",
        defaults={
            "storage_unit": "元",
            "display_unit": "亿元",
            "multiplier_to_storage": 100000000,
            "is_active": True,
            "priority": 0,
            "description": "test rule",
        },
    )
    fact = MacroFactModel.objects.create(
        indicator_code="CN_NEW_CREDIT",
        reporting_period="2026-03-01",
        value="31522.000000",
        unit="亿元",
        source="AKShare Public",
        published_at="2026-03-16",
        quality="valid",
        extra={},
    )

    stdout = StringIO()
    call_command("normalize_macro_fact_units", "--indicator-codes", "CN_NEW_CREDIT", stdout=stdout)

    fact.refresh_from_db()
    assert float(fact.value) == pytest.approx(31522.0 * 100000000.0)
    assert fact.unit == "元"
    assert fact.extra["original_unit"] == "亿元"
    assert fact.extra["display_unit"] == "亿元"
    assert fact.extra["dimension_key"] == "currency"
    assert fact.extra["multiplier_to_storage"] == 100000000.0
    assert fact.extra["matched_rule_id"] == rule.id
    assert fact.extra["publication_lag_days"] == 15
    assert "updated=1" in stdout.getvalue()
