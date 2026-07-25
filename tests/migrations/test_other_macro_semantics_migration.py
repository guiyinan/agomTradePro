"""Migration coverage for employment, housing, and refined-oil semantics."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_repairs_other_macro_catalogs_and_legacy_facts() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0044_quarantine_mislabeled_high_frequency_facts")])
        old_apps = executor.loader.project_state(
            [("data_center", "0044_quarantine_mislabeled_high_frequency_facts")]
        ).apps
        OldCatalog = old_apps.get_model("data_center", "IndicatorCatalogModel")
        Fact = old_apps.get_model("data_center", "MacroFactModel")
        old_house = OldCatalog.objects.get(code="CN_NEW_HOUSE_PRICE")
        old_oil = OldCatalog.objects.get(code="CN_OIL_PRICE")
        prior_house_name = old_house.name_cn
        prior_house_description = old_house.description
        prior_oil_name = old_oil.name_cn
        prior_oil_description = old_oil.description
        prior_oil_unit = old_oil.default_unit

        Fact.objects.create(
            indicator_code="CN_UNEMPLOYMENT",
            reporting_period="2026-05-01",
            value=Decimal("0"),
            unit="%",
            source="akshare",
            quality="valid",
        )
        Fact.objects.create(
            indicator_code="CN_UNEMPLOYMENT",
            reporting_period="2026-06-01",
            value=Decimal("5.2"),
            unit="%",
            source="akshare",
            quality="valid",
        )
        Fact.objects.create(
            indicator_code="CN_OIL_PRICE",
            reporting_period="2026-05-01",
            value=Decimal("6"),
            unit="元/升",
            source="akshare",
            quality="valid",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0045_correct_other_macro_fact_semantics")])
        new_apps = executor.loader.project_state(
            [("data_center", "0045_correct_other_macro_fact_semantics")]
        ).apps
        NewCatalog = new_apps.get_model("data_center", "IndicatorCatalogModel")
        NewRule = new_apps.get_model("data_center", "IndicatorUnitRuleModel")
        NewFact = new_apps.get_model("data_center", "MacroFactModel")

        house = NewCatalog.objects.get(code="CN_NEW_HOUSE_PRICE")
        oil = NewCatalog.objects.get(code="CN_OIL_PRICE")
        assert house.name_cn == "北京新建商品住宅价格同比变动"
        assert house.extra["geographic_scope"] == "city"
        assert house.extra["city"] == "北京"
        assert oil.default_unit == "元/吨"

        oil_rule = NewRule.objects.get(
            indicator_code="CN_OIL_PRICE",
            source_type="",
            original_unit="元/吨",
        )
        assert oil_rule.storage_unit == "元/吨"
        assert oil_rule.multiplier_to_storage == Decimal("1")

        repaired_oil = NewFact.objects.get(indicator_code="CN_OIL_PRICE")
        assert repaired_oil.value == Decimal("8160")
        assert repaired_oil.unit == "元/吨"
        assert repaired_oil.extra["value_before_unit_correction"] == "6.000000"

        invalid_zero = NewFact.objects.get(
            indicator_code="CN_UNEMPLOYMENT",
            reporting_period="2026-05-01",
        )
        valid_rate = NewFact.objects.get(
            indicator_code="CN_UNEMPLOYMENT",
            reporting_period="2026-06-01",
        )
        assert invalid_zero.quality == "error"
        assert invalid_zero.extra["quality_before_other_macro_semantics_correction"] == ("valid")
        assert valid_rate.quality == "valid"

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0044_quarantine_mislabeled_high_frequency_facts")])
        restored_apps = executor.loader.project_state(
            [("data_center", "0044_quarantine_mislabeled_high_frequency_facts")]
        ).apps
        RestoredCatalog = restored_apps.get_model("data_center", "IndicatorCatalogModel")
        RestoredRule = restored_apps.get_model("data_center", "IndicatorUnitRuleModel")
        RestoredFact = restored_apps.get_model("data_center", "MacroFactModel")

        restored_house = RestoredCatalog.objects.get(code="CN_NEW_HOUSE_PRICE")
        restored_oil = RestoredCatalog.objects.get(code="CN_OIL_PRICE")
        assert restored_house.name_cn == prior_house_name
        assert restored_house.description == prior_house_description
        assert restored_oil.name_cn == prior_oil_name
        assert restored_oil.description == prior_oil_description
        assert restored_oil.default_unit == prior_oil_unit
        assert RestoredRule.objects.filter(
            indicator_code="CN_OIL_PRICE",
            source_type="",
            original_unit="元/升",
        ).exists()

        restored_oil_fact = RestoredFact.objects.get(indicator_code="CN_OIL_PRICE")
        restored_zero = RestoredFact.objects.get(
            indicator_code="CN_UNEMPLOYMENT",
            reporting_period="2026-05-01",
        )
        assert restored_oil_fact.value == Decimal("6")
        assert restored_oil_fact.unit == "元/升"
        assert restored_zero.quality == "valid"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
