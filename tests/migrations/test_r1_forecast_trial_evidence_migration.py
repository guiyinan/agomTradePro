"""Migration evidence for the schema-only Research R1 trial ledger."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor

TABLE = "research_r1_forecast_trial_evidence"
BEFORE = [("research", "0019_r4_monitoring_owner_registry")]
AFTER = [("research", "0020_r1_forecast_trial_evidence")]


def test_0020_is_one_schema_only_table_with_exact_0019_dependency() -> None:
    migration = importlib.import_module(
        "apps.research.migrations.0020_r1_forecast_trial_evidence"
    ).Migration

    assert migration.dependencies == BEFORE
    assert [type(operation) for operation in migration.operations] == [migrations.CreateModel]
    assert [operation.name for operation in migration.operations] == [
        "R1ForecastTrialEvidenceLedgerModel"
    ]
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0020_forward_reverse_reforward_is_zero_seed() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(BEFORE)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        ledger = apps.get_model("research", "R1ForecastTrialEvidenceLedgerModel")
        assert ledger.objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        assert TABLE not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        ledger = apps.get_model("research", "R1ForecastTrialEvidenceLedgerModel")
        assert ledger.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0020_table_constraints_indexes_and_zero_seed_exist() -> None:
    assert TABLE in connection.introspection.table_names()
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, TABLE)
        cursor.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
        count = cursor.fetchone()

    assert {
        "res_r1_trial_ev_ident_uq",
        "res_r1_trial_def_ident_uq",
        "res_r1_trial_ev_clock_ck",
        "res_r1_trial_ev_safe_ck",
        "res_r1_trial_ev_pit_ix",
    } <= set(constraints)
    assert count == (0,)
