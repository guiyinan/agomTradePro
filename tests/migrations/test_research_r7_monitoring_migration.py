"""Migration evidence for schema-only R7 monitoring persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OBSERVATION_TABLE = "research_r7_monitoring_observation"
ASSESSMENT_TABLE = "research_r7_monitoring_assessment"
SNAPSHOT_TABLE = "research_r7_monitoring_audit_snapshot"
RESULT_TABLE = "research_r7_research_result"
LIFECYCLE_TABLE = "research_r7_result_lifecycle_event"


def test_0017_is_schema_only_and_depends_on_0016() -> None:
    module = importlib.import_module(
        "apps.research.migrations.0017_r7_post_promotion_monitoring_ledgers"
    )
    migration = module.Migration

    assert migration.dependencies == [("research", "0016_r2_trial_monitoring_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} <= {
        "CreateModel",
        "AddConstraint",
        "AddIndex",
    }
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0017_forward_reverse_reforward_is_zero_seed() -> None:
    before = [("research", "0016_r2_trial_monitoring_ledgers")]
    after = [("research", "0017_r7_post_promotion_monitoring_ledgers")]
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    tables = {OBSERVATION_TABLE, ASSESSMENT_TABLE, SNAPSHOT_TABLE}
    try:
        executor.migrate(before)
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        for model_name in (
            "R7MonitoringObservationLedgerModel",
            "R7MonitoringAssessmentLedgerModel",
            "R7MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        for model_name in (
            "R7MonitoringObservationLedgerModel",
            "R7MonitoringAssessmentLedgerModel",
            "R7MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0017_constraints_indexes_foreign_keys_and_zero_seed_exist() -> None:
    tables = {OBSERVATION_TABLE, ASSESSMENT_TABLE, SNAPSHOT_TABLE}
    assert tables <= set(connection.introspection.table_names())
    expected = {
        OBSERVATION_TABLE: {
            "res_r7_mon_obs_pit_ix",
            "res_r7_mon_obs_index_uq",
            "res_r7_mon_obs_ident_uq",
            "res_r7_mon_obs_clock_ck",
            "res_r7_mon_obs_safe_ck",
        },
        ASSESSMENT_TABLE: {
            "res_r7_mon_asmt_pit_ix",
            "res_r7_mon_asmt_cmd_uq",
            "res_r7_mon_asmt_clock_ck",
            "res_r7_mon_asmt_status_ck",
            "res_r7_mon_asmt_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r7_mon_snap_pit_ix",
            "res_r7_mon_snap_ident_uq",
            "res_r7_mon_snap_clock_ck",
            "res_r7_mon_snap_safe_ck",
        },
    }
    with connection.cursor() as cursor:
        constraints = {
            table: connection.introspection.get_constraints(cursor, table) for table in expected
        }
    for table, names in expected.items():
        assert names <= set(constraints[table])
    assessment_targets = {
        details["foreign_key"][0]
        for details in constraints[ASSESSMENT_TABLE].values()
        if details.get("foreign_key")
    }
    assert assessment_targets == {RESULT_TABLE, LIFECYCLE_TABLE}
    observation_targets = {
        details["foreign_key"][0]
        for details in constraints[OBSERVATION_TABLE].values()
        if details.get("foreign_key")
    }
    assert observation_targets == {
        ASSESSMENT_TABLE,
        RESULT_TABLE,
        LIFECYCLE_TABLE,
    }
    for table in expected:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
