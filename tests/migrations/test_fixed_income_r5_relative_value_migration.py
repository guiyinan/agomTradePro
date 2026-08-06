"""Migration evidence for the schema-only fixed-income R5 audit ledger."""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.db.migrations import CreateModel
from django.db.migrations.executor import MigrationExecutor

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_HISTORICAL_MIGRATION_HASHES = {
    "0001_initial.py": "201b740746c21cf86f22db535c849f0bce2edcca7b67da871c795ff7039103cf",
    "0002_seal_research_results.py": "15d271e90ffcaf3ee5590cf065ad5ef9c839885c1b92884d98b2dbf1402edc92",
}


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


def test_0003_is_create_only_and_preserves_0001_0002_migration_bytes() -> None:
    migration_directory = _REPOSITORY_ROOT / "apps" / "fixed_income" / "migrations"
    for filename, expected_hash in _HISTORICAL_MIGRATION_HASHES.items():
        assert sha256((migration_directory / filename).read_bytes()).hexdigest() == expected_hash

    migration = importlib.import_module(
        "apps.fixed_income.migrations.0003_r5_relative_value_audit_ledger"
    ).Migration
    assert migration.dependencies == [("fixed_income", "0002_seal_research_results")]
    assert len(migration.operations) == 2
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)


@pytest.mark.django_db(transaction=True)
def test_0003_preserves_legacy_sentinel_and_seeds_no_r5_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("fixed_income", "0002_seal_research_results")]
    after = [("fixed_income", "0003_r5_relative_value_audit_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        LegacyResult = old_apps.get_model(
            "fixed_income",
            "FixedIncomeResearchResultModel",
        )
        LegacyResult.objects.create(
            result_id="fixed-income:migration0003:sentinel",
            bond_id="BOND-MIGRATION-SENTINEL",
            valuation_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            settlement_date=date(2026, 8, 6),
            method_version="legacy-method.v1",
            input_hash="1" * 64,
            output_hash="2" * 64,
            status="blocked",
            payload={"sentinel": True},
            publication_ids=["publication:migration-sentinel"],
            blocked_reasons=["migration_sentinel"],
            research_only=True,
            must_not_execute=True,
            publication_evidence=[{"publication_id": "publication:migration-sentinel"}],
            must_not_use_for_decision=True,
        )
        expected_legacy_rows = _rows(LegacyResult)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        MigratedLegacyResult = new_apps.get_model(
            "fixed_income",
            "FixedIncomeResearchResultModel",
        )
        Receipt = new_apps.get_model(
            "fixed_income",
            "FixedIncomeR5InputReceiptModel",
        )
        Result = new_apps.get_model("fixed_income", "FixedIncomeR5ResultModel")

        assert _rows(MigratedLegacyResult) == expected_legacy_rows
        assert Receipt.objects.count() == 0
        assert Result.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
