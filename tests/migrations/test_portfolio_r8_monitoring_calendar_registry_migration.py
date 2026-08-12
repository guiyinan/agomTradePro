"""Schema-only migration proof for the Portfolio R8 calendar owner registry."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


def test_portfolio_0013_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The leaf creates exactly one empty owner table without data operations."""

    module = import_module(
        "apps.portfolio.migrations.0013_r8_monitoring_calendar_registry"
    )
    migration = module.Migration

    assert migration.dependencies == [
        ("portfolio", "0012_r4_monitoring_raw_fact_receipt")
    ]
    assert [type(operation) for operation in migration.operations] == [
        migrations.CreateModel
    ]
    assert [operation.name for operation in migration.operations] == [
        "R8MonitoringCalendarRegistryModel"
    ]
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_portfolio_0013_forward_reverse_reforward_stays_zero_seed() -> None:
    """Forward and reforward stay empty; reverse removes only the leaf table."""

    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    table = "portfolio_r8_monitoring_calendar_registry"
    prior = [("portfolio", "0012_r4_monitoring_raw_fact_receipt")]
    current = [("portfolio", "0013_r8_monitoring_calendar_registry")]
    try:
        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        model = apps.get_model("portfolio", "R8MonitoringCalendarRegistryModel")
        assert model._default_manager.count() == 0
        assert table in connection.introspection.table_names()

        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        model = apps.get_model("portfolio", "R8MonitoringCalendarRegistryModel")
        assert model._default_manager.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
