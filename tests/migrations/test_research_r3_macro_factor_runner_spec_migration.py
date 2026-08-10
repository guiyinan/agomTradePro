"""Migration evidence for the schema-only R3 runner-spec ledger."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

TABLE = "research_r3_macro_factor_runner_spec"


def test_0015_is_schema_only_and_depends_on_0014() -> None:
    module = importlib.import_module(
        "apps.research.migrations.0015_r3_macro_factor_runner_spec_ledger"
    )
    migration = module.Migration

    assert migration.dependencies == [("research", "0014_r5_monitoring_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0015_forward_reverse_reforward_remains_zero_seed() -> None:
    before = [("research", "0014_r5_monitoring_ledgers")]
    after = [("research", "0015_r3_macro_factor_runner_spec_ledger")]
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        model = apps.get_model("research", "R3MacroFactorRunnerSpecModel")
        assert model.objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        model = apps.get_model("research", "R3MacroFactorRunnerSpecModel")
        assert model.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0015_constraints_and_zero_seed_exist() -> None:
    assert TABLE in connection.introspection.table_names()
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, TABLE)
        cursor.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
        row_count = cursor.fetchone()

    assert {
        "res_r3_spec_identity_uq",
        "res_r3_spec_clock_ck",
        "res_r3_spec_safety_ck",
    } <= set(constraints)
    assert row_count == (0,)
