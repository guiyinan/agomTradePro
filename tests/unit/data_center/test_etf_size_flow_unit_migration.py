"""Regression coverage for ETF size-flow unit governance migration."""

from datetime import date
from importlib import import_module

import pytest
from django.apps import apps

from apps.data_center.infrastructure.models import IndicatorUnitRuleModel, MacroFactModel


@pytest.mark.django_db
def test_etf_size_flow_metadata_backfill_preserves_canonical_values() -> None:
    size_fact = MacroFactModel.objects.create(
        indicator_code="CN_A_ETF_SIZE_FLOW",
        reporting_period=date(2026, 7, 17),
        value=123_000_000,
        unit="元",
        source="tushare",
        extra={"source_type": "tushare", "original_unit": "万元"},
    )
    consensus_fact = MacroFactModel.objects.create(
        indicator_code="CN_A_ETF_NET_FLOW",
        reporting_period=date(2026, 7, 17),
        value=123_000_000,
        unit="元",
        source="data_center_consensus",
        extra={"source_type": "data_center_consensus", "original_unit": "万元"},
    )
    migration = import_module(
        "apps.data_center.migrations.0038_govern_etf_size_flow_unit"
    )

    migration.govern_etf_size_flow_unit(apps, None)

    size_rule = IndicatorUnitRuleModel.objects.get(
        indicator_code="CN_A_ETF_SIZE_FLOW",
        source_type="tushare",
        original_unit="万元",
    )
    size_fact.refresh_from_db()
    consensus_fact.refresh_from_db()
    assert size_fact.value == consensus_fact.value == 123_000_000
    assert size_fact.extra["matched_rule_id"] == size_rule.id
    assert size_fact.extra["multiplier_to_storage"] == 10_000.0
    assert consensus_fact.extra["original_unit"] == "元"
    assert consensus_fact.extra["multiplier_to_storage"] == 1.0
