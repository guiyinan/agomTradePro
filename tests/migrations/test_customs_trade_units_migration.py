"""Migration coverage for customs source units and derived trade balance."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_governs_customs_units_and_quarantines_old_balance() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0045_correct_other_macro_fact_semantics")])
        old_apps = executor.loader.project_state(
            [("data_center", "0045_correct_other_macro_fact_semantics")]
        ).apps
        OldCatalog = old_apps.get_model("data_center", "IndicatorCatalogModel")
        OldRule = old_apps.get_model("data_center", "IndicatorUnitRuleModel")
        OldFact = old_apps.get_model("data_center", "MacroFactModel")
        balance = OldCatalog.objects.get(code="CN_TRADE_BALANCE")
        prior_description = balance.description
        prior_derivation_present = "derivation_method" in dict(balance.extra or {})
        assert not OldRule.objects.filter(
            indicator_code__in=("CN_EXPORTS", "CN_IMPORTS", "CN_TRADE_BALANCE"),
            source_type="akshare",
            original_unit="千美元",
        ).exists()
        OldFact.objects.create(
            indicator_code="CN_TRADE_BALANCE",
            reporting_period="2026-06-09",
            value=Decimal("1032.2"),
            unit="亿美元",
            source="akshare",
            quality="valid",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0046_govern_customs_trade_units")])
        new_apps = executor.loader.project_state(
            [("data_center", "0046_govern_customs_trade_units")]
        ).apps
        NewCatalog = new_apps.get_model("data_center", "IndicatorCatalogModel")
        NewRule = new_apps.get_model("data_center", "IndicatorUnitRuleModel")
        NewFact = new_apps.get_model("data_center", "MacroFactModel")

        rules = NewRule.objects.filter(
            indicator_code__in=("CN_EXPORTS", "CN_IMPORTS", "CN_TRADE_BALANCE"),
            source_type="akshare",
            original_unit="千美元",
        )
        assert rules.count() == 3
        assert all(rule.storage_unit == "元" for rule in rules)
        assert all(rule.display_unit == "亿美元" for rule in rules)
        assert all(rule.multiplier_to_storage == Decimal("1000") for rule in rules)

        migrated_balance = NewCatalog.objects.get(code="CN_TRADE_BALANCE")
        assert migrated_balance.extra["upstream_indicator_codes"] == [
            "CN_EXPORTS",
            "CN_IMPORTS",
        ]
        old_fact = NewFact.objects.get(indicator_code="CN_TRADE_BALANCE")
        assert old_fact.quality == "error"
        assert old_fact.extra["quality_before_trade_balance_derivation"] == "valid"

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0045_correct_other_macro_fact_semantics")])
        restored_apps = executor.loader.project_state(
            [("data_center", "0045_correct_other_macro_fact_semantics")]
        ).apps
        RestoredCatalog = restored_apps.get_model("data_center", "IndicatorCatalogModel")
        RestoredRule = restored_apps.get_model("data_center", "IndicatorUnitRuleModel")
        RestoredFact = restored_apps.get_model("data_center", "MacroFactModel")

        restored_balance = RestoredCatalog.objects.get(code="CN_TRADE_BALANCE")
        assert restored_balance.description == prior_description
        assert (
            "derivation_method" in dict(restored_balance.extra or {})
        ) is prior_derivation_present
        assert not RestoredRule.objects.filter(
            indicator_code__in=("CN_EXPORTS", "CN_IMPORTS", "CN_TRADE_BALANCE"),
            source_type="akshare",
            original_unit="千美元",
        ).exists()
        restored_fact = RestoredFact.objects.get(indicator_code="CN_TRADE_BALANCE")
        assert restored_fact.quality == "valid"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
