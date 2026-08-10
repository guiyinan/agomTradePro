"""Migration evidence for schema-only R7 family lifecycle persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

AUTHORIZATION_TABLE = "research_r7_family_lifecycle_authorization"
EVENT_TABLE = "research_r7_family_lifecycle_event"
COMMIT_TABLE = "research_r7_family_lifecycle_stream_commit"
SNAPSHOT_TABLE = "research_r7_family_lifecycle_audit_snapshot"
RESULT_TABLE = "research_r7_research_result"
LOCAL_EVENT_TABLE = "research_r7_result_lifecycle_event"


def test_0018_is_schema_only_and_depends_on_0017() -> None:
    module = importlib.import_module(
        "apps.research.migrations.0018_r7_result_family_lifecycle_ledgers"
    )
    migration = module.Migration

    assert migration.dependencies == [("research", "0017_r7_post_promotion_monitoring_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} <= {
        "CreateModel",
        "AddConstraint",
        "AddIndex",
    }
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0018_forward_reverse_reforward_is_zero_seed() -> None:
    before = [("research", "0017_r7_post_promotion_monitoring_ledgers")]
    after = [("research", "0018_r7_result_family_lifecycle_ledgers")]
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    tables = {AUTHORIZATION_TABLE, EVENT_TABLE, COMMIT_TABLE, SNAPSHOT_TABLE}
    model_names = (
        "R7FamilyLifecycleAuthorizationModel",
        "R7FamilyLifecycleEventModel",
        "R7FamilyLifecycleStreamCommitModel",
        "R7FamilyLifecycleAuditSnapshotModel",
    )
    try:
        executor.migrate(before)
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        assert all(apps.get_model("research", name).objects.count() == 0 for name in model_names)

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        assert all(apps.get_model("research", name).objects.count() == 0 for name in model_names)
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0018_constraints_foreign_keys_and_zero_seed_exist() -> None:
    tables = {AUTHORIZATION_TABLE, EVENT_TABLE, COMMIT_TABLE, SNAPSHOT_TABLE}
    assert tables <= set(connection.introspection.table_names())
    expected = {
        AUTHORIZATION_TABLE: {
            "res_r7_fam_auth_pit_idx",
            "res_r7_fam_auth_ident_uq",
            "res_r7_fam_auth_event_uq",
            "res_r7_fam_auth_clock_ck",
            "res_r7_fam_auth_prev_ck",
            "res_r7_fam_auth_target_ck",
        },
        EVENT_TABLE: {
            "res_r7_fam_evt_pit_idx",
            "res_r7_fam_evt_ident_uq",
            "res_r7_fam_evt_id_seq_uq",
            "res_r7_fam_evt_hash_seq_uq",
            "res_r7_fam_evt_clock_ck",
            "res_r7_fam_evt_prev_ck",
            "res_r7_fam_evt_target_ck",
        },
        COMMIT_TABLE: {
            "res_r7_fam_com_id_seq_uq",
            "res_r7_fam_com_hash_seq_uq",
            "res_r7_fam_com_auth_uq",
            "res_r7_fam_com_event_uq",
        },
        SNAPSHOT_TABLE: {
            "res_r7_fam_audit_ident_uq",
            "res_r7_fam_audit_clock_ck",
        },
    }
    with connection.cursor() as cursor:
        constraints = {
            table: connection.introspection.get_constraints(cursor, table) for table in expected
        }
    for table, names in expected.items():
        assert names <= set(constraints[table])
    authorization_targets = {
        details["foreign_key"][0]
        for details in constraints[AUTHORIZATION_TABLE].values()
        if details.get("foreign_key")
    }
    assert authorization_targets == {RESULT_TABLE, LOCAL_EVENT_TABLE}
    event_targets = {
        details["foreign_key"][0]
        for details in constraints[EVENT_TABLE].values()
        if details.get("foreign_key")
    }
    assert event_targets == {AUTHORIZATION_TABLE, RESULT_TABLE, LOCAL_EVENT_TABLE}
    commit_targets = {
        details["foreign_key"][0]
        for details in constraints[COMMIT_TABLE].values()
        if details.get("foreign_key")
    }
    assert commit_targets == {AUTHORIZATION_TABLE, EVENT_TABLE}
    for table in expected:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
