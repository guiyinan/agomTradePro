"""Migration evidence for the schema-only R2 trial-policy registry."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

TABLE = "research_r2_trial_policy_registry"


def test_0021_is_schema_only_and_depends_exactly_on_0020() -> None:
    module = importlib.import_module("apps.research.migrations.0021_r2_trial_policy_registry")
    migration = module.Migration

    assert migration.dependencies == [("research", "0020_r1_forecast_trial_evidence")]
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0021_forward_reverse_reforward_remains_zero_seed() -> None:
    before = [("research", "0020_r1_forecast_trial_evidence")]
    after = [("research", "0021_r2_trial_policy_registry")]
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        model = apps.get_model("research", "R2MarketStructureTrialPolicyLedgerModel")
        assert model.objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        model = apps.get_model("research", "R2MarketStructureTrialPolicyLedgerModel")
        assert model.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0021_constraints_index_and_zero_seed_exist() -> None:
    assert TABLE in connection.introspection.table_names()
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, TABLE)
        cursor.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
        row_count = cursor.fetchone()

    assert {
        "res_r2_pol_ident_uq",
        "res_r2_pol_clock_ck",
        "res_r2_pol_safe_ck",
        "res_r2_pol_pit_ix",
    } <= set(constraints)
    assert row_count == (0,)
