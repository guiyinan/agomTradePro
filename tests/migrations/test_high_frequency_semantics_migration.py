"""Migration coverage for mislabeled high-frequency macro facts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_disables_sync_and_quarantines_mislabeled_facts() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0043_govern_manual_pmi_subitem_provenance")])
        old_apps = executor.loader.project_state(
            [("data_center", "0043_govern_manual_pmi_subitem_provenance")]
        ).apps
        Catalog = old_apps.get_model("data_center", "IndicatorCatalogModel")
        Fact = old_apps.get_model("data_center", "MacroFactModel")

        for code in ("CN_NHCI", "CN_FX_CENTER"):
            catalog = Catalog.objects.get(code=code)
            extra = dict(catalog.extra or {})
            extra["governance_sync_supported"] = True
            catalog.extra = extra
            catalog.save(update_fields=["extra"])
            Fact.objects.create(
                indicator_code=code,
                reporting_period="2026-07-01",
                value=Decimal("100.000000"),
                unit="指数" if code == "CN_NHCI" else "",
                source="akshare",
                quality="valid",
            )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0044_quarantine_mislabeled_high_frequency_facts")])
        new_apps = executor.loader.project_state(
            [("data_center", "0044_quarantine_mislabeled_high_frequency_facts")]
        ).apps
        NewCatalog = new_apps.get_model("data_center", "IndicatorCatalogModel")
        NewFact = new_apps.get_model("data_center", "MacroFactModel")

        for code in ("CN_NHCI", "CN_FX_CENTER"):
            catalog = NewCatalog.objects.get(code=code)
            fact = NewFact.objects.get(indicator_code=code, source="akshare")
            assert catalog.extra["governance_sync_supported"] is False
            assert fact.quality == "error"
            assert fact.extra["invalidated_by_migration"].startswith("0044_")
            assert fact.extra["quality_before_high_frequency_semantics_correction"] == ("valid")
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
