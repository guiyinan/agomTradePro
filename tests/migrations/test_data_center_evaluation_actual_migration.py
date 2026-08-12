"""Migration evidence for schema-only Data Center R1 actual ledgers."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

SOURCE_TABLE = "data_center_evaluation_actual_source"
MANIFEST_TABLE = "data_center_evaluation_actual_manifest"
TABLES = {SOURCE_TABLE, MANIFEST_TABLE}
BEFORE = [("data_center", "0067_move_provider_credentials_to_config_center")]
AFTER = [("data_center", "0068_evaluation_actual_ledgers")]


def test_0068_is_schema_only_and_has_the_exact_0067_dependency() -> None:
    module = importlib.import_module("apps.data_center.migrations.0068_evaluation_actual_ledgers")
    migration = module.Migration

    assert migration.dependencies == BEFORE
    assert len(migration.operations) == 2
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0068_forward_reverse_reforward_is_zero_seed() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(BEFORE)
        assert TABLES.isdisjoint(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        source = apps.get_model("data_center", "EvaluationActualSourceDefinitionModel")
        manifest = apps.get_model("data_center", "EvaluationActualManifestReceiptModel")
        assert source.objects.count() == 0
        assert manifest.objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        assert TABLES.isdisjoint(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        source = apps.get_model("data_center", "EvaluationActualSourceDefinitionModel")
        manifest = apps.get_model("data_center", "EvaluationActualManifestReceiptModel")
        assert source.objects.count() == 0
        assert manifest.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0068_tables_constraints_indexes_and_protected_fk_exist() -> None:
    assert TABLES <= set(connection.introspection.table_names())
    expected = {
        SOURCE_TABLE: {
            "dc_evact_source_identity_uq",
            "dc_evact_source_sem_ck",
            "dc_evact_source_safe_ck",
            "dc_evact_source_pit_idx",
        },
        MANIFEST_TABLE: {
            "dc_evact_manifest_identity_uq",
            "dc_evact_manifest_sem_ck",
            "dc_evact_manifest_safe_ck",
            "dc_evact_manifest_pit_idx",
            "dc_evact_manifest_src_idx",
        },
    }
    with connection.cursor() as cursor:
        for table, names in expected.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            assert names <= set(constraints)
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
        manifest_constraints = connection.introspection.get_constraints(cursor, MANIFEST_TABLE)

    foreign_targets = {
        details["foreign_key"][0]
        for details in manifest_constraints.values()
        if details.get("foreign_key")
    }
    assert foreign_targets == {SOURCE_TABLE}
