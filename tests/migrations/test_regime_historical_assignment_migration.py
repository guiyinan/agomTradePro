"""Schema-only migration proof for Regime historical assignments."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations import CreateModel, RunPython, RunSQL
from django.db.migrations.executor import MigrationExecutor


def test_regime_0010_is_schema_only_and_zero_seed_by_construction() -> None:
    migration = import_module(
        "apps.regime.migrations.0010_historical_assignment_registry"
    ).Migration

    assert migration.dependencies == [("regime", "0009_use_native_regime_display_labels")]
    assert len(migration.operations) == 2
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_regime_0010_forward_reverse_reforward_stays_zero_seed() -> None:
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    tables = {
        "regime_historical_assignment_definition",
        "regime_historical_assignment_receipt",
    }
    try:
        MigrationExecutor(connection).migrate([("regime", "0009_use_native_regime_display_labels")])
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate([("regime", "0010_historical_assignment_registry")])
        apps = executor.loader.project_state(
            [("regime", "0010_historical_assignment_registry")]
        ).apps
        assert (
            apps.get_model(
                "regime", "HistoricalRegimeAssignmentDefinitionModel"
            )._default_manager.count()
            == 0
        )
        assert (
            apps.get_model(
                "regime", "HistoricalRegimeAssignmentReceiptModel"
            )._default_manager.count()
            == 0
        )

        MigrationExecutor(connection).migrate([("regime", "0009_use_native_regime_display_labels")])
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate([("regime", "0010_historical_assignment_registry")])
        apps = executor.loader.project_state(
            [("regime", "0010_historical_assignment_registry")]
        ).apps
        assert (
            apps.get_model(
                "regime", "HistoricalRegimeAssignmentDefinitionModel"
            )._default_manager.count()
            == 0
        )
        assert (
            apps.get_model(
                "regime", "HistoricalRegimeAssignmentReceiptModel"
            )._default_manager.count()
            == 0
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
