"""Schema-only migration proof for the Signal realization-source registry."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations import CreateModel, RunPython
from django.db.migrations.executor import MigrationExecutor


def test_signal_0012_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The migration creates exactly two empty tables and has no data operation."""

    module = import_module("apps.signal.migrations.0012_forecast_realization_source_definition")
    migration = module.Migration

    assert migration.dependencies == [("signal", "0011_forecast_realization_owner")]
    assert [operation.name for operation in migration.operations] == [
        "ForecastRealizationSourceDefinitionModel",
        "ForecastRealizationSourceDefinitionMemberModel",
    ]
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_signal_0012_forward_reverse_reforward_stays_zero_seed() -> None:
    """Forward and reforward create empty tables; reverse removes only 0012."""

    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    definition_table = "signal_forecast_realization_source_definition"
    member_table = "signal_forecast_realization_source_definition_member"
    owner_table = "signal_forecast_realization_manifest"
    try:
        MigrationExecutor(connection).migrate([("signal", "0011_forecast_realization_owner")])
        assert owner_table in connection.introspection.table_names()
        assert definition_table not in connection.introspection.table_names()
        assert member_table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0012_forecast_realization_source_definition")])
        apps = executor.loader.project_state(
            [("signal", "0012_forecast_realization_source_definition")]
        ).apps
        Definition = apps.get_model("signal", "ForecastRealizationSourceDefinitionModel")
        Member = apps.get_model("signal", "ForecastRealizationSourceDefinitionMemberModel")
        assert Definition._default_manager.count() == 0
        assert Member._default_manager.count() == 0

        MigrationExecutor(connection).migrate([("signal", "0011_forecast_realization_owner")])
        assert owner_table in connection.introspection.table_names()
        assert definition_table not in connection.introspection.table_names()
        assert member_table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0012_forecast_realization_source_definition")])
        apps = executor.loader.project_state(
            [("signal", "0012_forecast_realization_source_definition")]
        ).apps
        assert (
            apps.get_model(
                "signal", "ForecastRealizationSourceDefinitionModel"
            )._default_manager.count()
            == 0
        )
        assert (
            apps.get_model(
                "signal", "ForecastRealizationSourceDefinitionMemberModel"
            )._default_manager.count()
            == 0
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
