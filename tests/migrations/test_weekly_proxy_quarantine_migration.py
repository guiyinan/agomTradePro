"""Migration coverage for semantically incompatible weekly proxy facts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

INDICATOR_CODES = (
    "CN_POWER_GEN",
    "CN_BLAST_FURNACE",
    "CN_CCFI",
    "CN_SCFI",
)


@pytest.mark.django_db(transaction=True)
def test_migration_disables_and_quarantines_weekly_proxy_facts() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0046_govern_customs_trade_units")])
        old_apps = executor.loader.project_state(
            [("data_center", "0046_govern_customs_trade_units")]
        ).apps
        OldCatalog = old_apps.get_model("data_center", "IndicatorCatalogModel")
        OldFact = old_apps.get_model("data_center", "MacroFactModel")
        prior_descriptions = {}
        for index, code in enumerate(INDICATOR_CODES, start=1):
            catalog = OldCatalog.objects.get(code=code)
            prior_descriptions[code] = catalog.description
            OldFact.objects.create(
                indicator_code=code,
                reporting_period=f"2026-0{index}-01",
                value=Decimal(str(index * 100)),
                unit=catalog.default_unit,
                source="akshare",
                quality="valid",
            )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0047_quarantine_weekly_proxy_facts")])
        new_apps = executor.loader.project_state(
            [("data_center", "0047_quarantine_weekly_proxy_facts")]
        ).apps
        NewCatalog = new_apps.get_model("data_center", "IndicatorCatalogModel")
        NewFact = new_apps.get_model("data_center", "MacroFactModel")

        for code in INDICATOR_CODES:
            catalog = NewCatalog.objects.get(code=code)
            fact = NewFact.objects.get(indicator_code=code, source="akshare")
            assert catalog.extra["governance_sync_supported"] is False
            assert catalog.extra["governance_status"] == "unsupported_proxy"
            assert fact.quality == "error"
            assert fact.extra["quality_before_weekly_proxy_quarantine"] == "valid"

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0046_govern_customs_trade_units")])
        restored_apps = executor.loader.project_state(
            [("data_center", "0046_govern_customs_trade_units")]
        ).apps
        RestoredCatalog = restored_apps.get_model("data_center", "IndicatorCatalogModel")
        RestoredFact = restored_apps.get_model("data_center", "MacroFactModel")
        for code in INDICATOR_CODES:
            catalog = RestoredCatalog.objects.get(code=code)
            fact = RestoredFact.objects.get(indicator_code=code, source="akshare")
            assert catalog.description == prior_descriptions[code]
            assert fact.quality == "valid"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
