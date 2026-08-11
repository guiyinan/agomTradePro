"""Schema-only migration proof for Signal R7 realization owner receipts."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations import CreateModel, RunPython
from django.db.migrations.executor import MigrationExecutor


def test_signal_0011_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The migration creates exactly two tables and contains no data operation."""

    module = import_module("apps.signal.migrations.0011_forecast_realization_owner")
    migration = module.Migration

    assert migration.dependencies == [("signal", "0010_scenario_forecast_binding")]
    assert [operation.name for operation in migration.operations] == [
        "ForecastRealizationManifestModel",
        "ForecastRealizationReceiptModel",
    ]
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_signal_0011_forward_reverse_reforward_stays_zero_seed() -> None:
    """Fresh forward creates empty tables and reverse removes only those tables."""

    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    manifest_table = "signal_forecast_realization_manifest"
    receipt_table = "signal_forecast_realization_receipt"
    try:
        MigrationExecutor(connection).migrate([("signal", "0010_scenario_forecast_binding")])
        assert manifest_table not in connection.introspection.table_names()
        assert receipt_table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0011_forecast_realization_owner")])
        apps = executor.loader.project_state([("signal", "0011_forecast_realization_owner")]).apps
        Manifest = apps.get_model("signal", "ForecastRealizationManifestModel")
        Receipt = apps.get_model("signal", "ForecastRealizationReceiptModel")
        assert Manifest._default_manager.count() == 0
        assert Receipt._default_manager.count() == 0

        MigrationExecutor(connection).migrate([("signal", "0010_scenario_forecast_binding")])
        assert manifest_table not in connection.introspection.table_names()
        assert receipt_table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0011_forecast_realization_owner")])
        apps = executor.loader.project_state([("signal", "0011_forecast_realization_owner")]).apps
        assert (
            apps.get_model("signal", "ForecastRealizationManifestModel")._default_manager.count()
            == 0
        )
        assert (
            apps.get_model("signal", "ForecastRealizationReceiptModel")._default_manager.count()
            == 0
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
