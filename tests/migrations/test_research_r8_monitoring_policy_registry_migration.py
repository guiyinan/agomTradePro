"""Schema-only migration proof for the Research R8 policy owner registry."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


def test_research_0023_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The leaf creates exactly one empty owner table without data operations."""

    module = import_module("apps.research.migrations.0023_r8_monitoring_policy_registry")
    migration = module.Migration
    assert migration.dependencies == [("research", "0022_r5_monitoring_owner_registry")]
    assert [type(operation) for operation in migration.operations] == [migrations.CreateModel]
    assert [operation.name for operation in migration.operations] == [
        "R8MonitoringPolicyRegistryModel"
    ]
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_research_0023_forward_reverse_reforward_stays_zero_seed() -> None:
    """Forward and reforward stay empty; reverse removes only the leaf table."""

    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes()
    table = "research_r8_monitoring_policy_registry"
    prior = [("research", "0022_r5_monitoring_owner_registry")]
    current = [("research", "0023_r8_monitoring_policy_registry")]
    try:
        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        model = apps.get_model("research", "R8MonitoringPolicyRegistryModel")
        assert model._default_manager.count() == 0
        assert table in connection.introspection.table_names()
        MigrationExecutor(connection).migrate(prior)
        assert table not in connection.introspection.table_names()
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        assert (
            apps.get_model("research", "R8MonitoringPolicyRegistryModel")._default_manager.count()
            == 0
        )
    finally:
        MigrationExecutor(connection).migrate(leaves)
