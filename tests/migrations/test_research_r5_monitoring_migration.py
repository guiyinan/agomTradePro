"""Migration evidence for schema-only R5 monitoring persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OBSERVATION_TABLE = "research_r5_monitoring_observation"
ASSESSMENT_TABLE = "research_r5_monitoring_assessment"
SNAPSHOT_TABLE = "research_r5_monitoring_audit_snapshot"
DECISION_TABLE = "research_r5_promotion_decision_bundle"
LIFECYCLE_TABLE = "research_r5_promotion_lifecycle_event"


def test_0014_is_schema_only_and_depends_on_0013() -> None:
    module = importlib.import_module("apps.research.migrations.0014_r5_monitoring_ledgers")
    migration = module.Migration

    assert migration.dependencies == [("research", "0013_r4_monitoring_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} <= {
        "CreateModel",
        "AddConstraint",
        "AddIndex",
    }
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0014_forward_reverse_reforward_is_zero_seed() -> None:
    before = [("research", "0013_r4_monitoring_ledgers")]
    after = [("research", "0014_r5_monitoring_ledgers")]
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
            "R5MonitoringObservationLedgerModel",
            "R5MonitoringAssessmentLedgerModel",
            "R5MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        for model_name in (
            "R5MonitoringObservationLedgerModel",
            "R5MonitoringAssessmentLedgerModel",
            "R5MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0014_constraints_indexes_fk_and_zero_seed_exist() -> None:
    tables = {OBSERVATION_TABLE, ASSESSMENT_TABLE, SNAPSHOT_TABLE}
    assert tables <= set(connection.introspection.table_names())
    expected = {
        OBSERVATION_TABLE: {
            "res_r5_mon_obs_pit_ix",
            "res_r5_mon_obs_period_uq",
            "res_r5_mon_obs_clock_ck",
            "res_r5_mon_obs_safe_ck",
        },
        ASSESSMENT_TABLE: {
            "res_r5_mon_asmt_pit_ix",
            "res_r5_mon_asmt_cmd_uq",
            "res_r5_mon_asmt_clock_ck",
            "res_r5_mon_asmt_status_ck",
            "res_r5_mon_asmt_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r5_mon_snap_pit_ix",
            "res_r5_mon_snap_ident_uq",
            "res_r5_mon_snap_clock_ck",
            "res_r5_mon_snap_safe_ck",
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
    assert assessment_targets == {DECISION_TABLE, LIFECYCLE_TABLE}
    observation_targets = {
        details["foreign_key"][0]
        for details in constraints[OBSERVATION_TABLE].values()
        if details.get("foreign_key")
    }
    assert observation_targets == {
        ASSESSMENT_TABLE,
        DECISION_TABLE,
        LIFECYCLE_TABLE,
    }
    for table in expected:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
