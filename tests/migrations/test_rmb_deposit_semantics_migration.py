from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps

from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    MacroFactModel,
)


@pytest.mark.django_db
def test_rmb_deposit_semantics_migration_quarantines_only_legacy_akshare_facts():
    migration = import_module("apps.data_center.migrations.0041_correct_rmb_deposit_semantics")
    catalog = IndicatorCatalogModel.objects.get(code="CN_RMB_DEPOSIT")
    catalog.name_cn = "人民币存款余额"
    catalog.description = "legacy balance semantics"
    catalog.extra = {
        **dict(catalog.extra or {}),
        "series_semantics": "balance_level",
        "chart_policy": "continuous_line",
    }
    catalog.save(update_fields=["name_cn", "description", "extra"])

    akshare_fact = MacroFactModel.objects.create(
        indicator_code="CN_RMB_DEPOSIT",
        reporting_period=date(2026, 1, 31),
        value=Decimal("3500"),
        unit="亿元",
        source="akshare",
        quality="valid",
    )
    other_fact = MacroFactModel.objects.create(
        indicator_code="CN_RMB_DEPOSIT",
        reporting_period=date(2026, 1, 31),
        value=Decimal("12000"),
        unit="亿元",
        source="tushare",
        quality="valid",
    )

    migration.correct_rmb_deposit_semantics(apps, None)

    catalog.refresh_from_db()
    akshare_fact.refresh_from_db()
    other_fact.refresh_from_db()
    assert catalog.name_cn == "新增人民币存款"
    assert catalog.extra["series_semantics"] == "flow_level"
    assert catalog.extra["chart_policy"] == "period_bar"
    assert akshare_fact.quality == "error"
    assert akshare_fact.extra["invalidated_by_migration"] == "0041_correct_rmb_deposit_semantics"
    assert akshare_fact.extra["quality_before_rmb_deposit_semantics_correction"] == "valid"
    assert other_fact.quality == "valid"
    assert other_fact.extra == {}

    migration.restore_rmb_deposit_semantics(apps, None)

    akshare_fact.refresh_from_db()
    assert akshare_fact.quality == "valid"
    assert "invalidated_by_migration" not in akshare_fact.extra
