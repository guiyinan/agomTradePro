"""Migration coverage for the macro governance closure."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_macro_governance_closure_repairs_seeds_and_backfills_metadata() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0032_productioncoverageuniverseconfigmodel")])
        old_apps = executor.loader.project_state(
            [("data_center", "0032_productioncoverageuniverseconfigmodel")]
        ).apps
        Catalog = old_apps.get_model("data_center", "IndicatorCatalogModel")
        Rule = old_apps.get_model("data_center", "IndicatorUnitRuleModel")
        Fact = old_apps.get_model("data_center", "MacroFactModel")

        etf = Catalog.objects.get(code="CN_A_ETF_NET_FLOW_MAIN")
        etf.extra = {"series_semantics": "flow_level", "chart_policy": "period_bar"}
        etf.save(update_fields=["extra"])

        term = Catalog.objects.get(code="CN_TERM_SPREAD_10Y2Y")
        term.default_unit = "%"
        term.save(update_fields=["default_unit"])
        Rule.objects.filter(indicator_code=term.code).delete()
        Rule.objects.create(
            indicator_code=term.code,
            source_type="",
            original_unit="%",
            dimension_key="rate",
            storage_unit="%",
            display_unit="%",
            multiplier_to_storage=Decimal("1"),
            is_active=True,
            priority=0,
        )
        Fact.objects.create(
            indicator_code=term.code,
            reporting_period="2026-05-30",
            value=Decimal("42.000000"),
            unit="%",
            source="data_center",
            extra={"source_type": "data_center"},
        )

        Catalog.objects.create(
            code="TMP_MIGRATION_GOVERNANCE",
            name_cn="迁移治理测试",
            default_unit="元",
            default_period_type="M",
            is_active=True,
        )
        rule = Rule.objects.create(
            indicator_code="TMP_MIGRATION_GOVERNANCE",
            source_type="",
            original_unit="",
            dimension_key="currency",
            storage_unit="元",
            display_unit="亿元",
            multiplier_to_storage=Decimal("1"),
            is_active=True,
            priority=0,
        )
        Fact.objects.create(
            indicator_code="TMP_MIGRATION_GOVERNANCE",
            reporting_period="2026-05-31",
            published_at="2026-06-10",
            value=Decimal("123.000000"),
            unit="元",
            source="manual_import",
            extra={},
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0033_close_macro_fact_governance_gaps")])
        new_apps = executor.loader.project_state(
            [("data_center", "0033_close_macro_fact_governance_gaps")]
        ).apps
        NewCatalog = new_apps.get_model("data_center", "IndicatorCatalogModel")
        NewRule = new_apps.get_model("data_center", "IndicatorUnitRuleModel")
        NewFact = new_apps.get_model("data_center", "MacroFactModel")

        migrated_etf = NewCatalog.objects.get(code="CN_A_ETF_NET_FLOW_MAIN")
        assert migrated_etf.extra["chart_reset_frequency"] == ""
        assert migrated_etf.extra["chart_segment_basis"] == ""
        assert migrated_etf.extra["regime_input_policy"] == "direct_allowed"

        migrated_term = NewCatalog.objects.get(code="CN_TERM_SPREAD_10Y2Y")
        assert migrated_term.default_unit == "BP"
        migrated_term_rule = NewRule.objects.get(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            source_type="",
        )
        assert migrated_term_rule.original_unit == "BP"
        assert migrated_term_rule.storage_unit == "BP"
        assert migrated_term_rule.display_unit == "BP"
        migrated_term_fact = NewFact.objects.get(indicator_code="CN_TERM_SPREAD_10Y2Y")
        assert migrated_term_fact.value == Decimal("42.000000")
        assert migrated_term_fact.unit == "BP"

        migrated_fact = NewFact.objects.get(indicator_code="TMP_MIGRATION_GOVERNANCE")
        assert migrated_fact.value == Decimal("123.000000")
        assert migrated_fact.unit == "元"
        assert migrated_fact.extra == {
            "source_type": "manual_import",
            "original_unit": "元",
            "display_unit": "亿元",
            "dimension_key": "currency",
            "multiplier_to_storage": 1.0,
            "matched_rule_id": rule.id,
            "period_type": "M",
            "publication_lag_days": 10,
        }
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
