"""Schema-only migration proof for the Broker R8 reconciliation receipt registry."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


def test_broker_0007_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The leaf creates exactly one empty owner table without data operations."""

    module = import_module(
        "apps.broker_execution.migrations.0007_r8_monitoring_reconciliation_receipt"
    )
    migration = module.Migration

    assert migration.dependencies == [("broker_execution", "0006_nullable_audit_owner")]
    assert [type(operation) for operation in migration.operations] == [migrations.CreateModel]
    assert [operation.name for operation in migration.operations] == [
        "R8BrokerMonitoringPeriodReceiptModel"
    ]
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_broker_0007_forward_reverse_reforward_stays_zero_seed() -> None:
    """Forward and reforward stay empty; reverse removes only the leaf table."""

    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    table = "broker_execution_r8_monitoring_period_receipt"
    prior = [("broker_execution", "0006_nullable_audit_owner")]
    current = [("broker_execution", "0007_r8_monitoring_reconciliation_receipt")]
    try:
        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        model = apps.get_model("broker_execution", "R8BrokerMonitoringPeriodReceiptModel")
        assert model._default_manager.count() == 0
        assert table in connection.introspection.table_names()

        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        model = apps.get_model("broker_execution", "R8BrokerMonitoringPeriodReceiptModel")
        assert model._default_manager.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
