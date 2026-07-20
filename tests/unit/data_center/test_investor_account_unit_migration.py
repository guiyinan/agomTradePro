"""Regression coverage for investor-account unit metadata backfill."""

from datetime import date
from importlib import import_module

import pytest
from django.apps import apps

from apps.data_center.infrastructure.models import IndicatorUnitRuleModel, MacroFactModel


@pytest.mark.django_db
def test_investor_account_metadata_backfill_is_idempotent() -> None:
    rule = IndicatorUnitRuleModel.objects.get(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        source_type="akshare",
        original_unit="万户",
    )
    fact = MacroFactModel.objects.create(
        indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
        reporting_period=date(2026, 6, 30),
        value=3_098_700,
        unit="户",
        source="akshare",
        extra={
            "source_type": "akshare",
            "original_unit": "万户",
            "matched_rule_id": 1,
            "multiplier_to_storage": 1.0,
        },
    )
    migration = import_module(
        "apps.data_center.migrations.0037_backfill_investor_account_unit_metadata"
    )

    migration.backfill_investor_account_unit_metadata(apps, None)
    migration.backfill_investor_account_unit_metadata(apps, None)

    fact.refresh_from_db()
    assert fact.value == 3_098_700
    assert fact.unit == "户"
    assert fact.extra["matched_rule_id"] == rule.id
    assert fact.extra["multiplier_to_storage"] == 10_000.0
