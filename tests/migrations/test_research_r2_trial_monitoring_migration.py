"""Migration evidence for schema-only R2 trial-monitoring persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

TRIAL_TABLE = "research_r2_explanatory_trial_assessment"
OBSERVATION_TABLE = "research_r2_monitoring_observation"
ASSESSMENT_TABLE = "research_r2_monitoring_assessment"
SNAPSHOT_TABLE = "research_r2_monitoring_audit_snapshot"
TABLES = {TRIAL_TABLE, OBSERVATION_TABLE, ASSESSMENT_TABLE, SNAPSHOT_TABLE}


def test_0016_is_schema_only_and_depends_on_0015() -> None:
    module = importlib.import_module("apps.research.migrations.0016_r2_trial_monitoring_ledgers")
    migration = module.Migration

    assert migration.dependencies == [("research", "0015_r3_macro_factor_runner_spec_ledger")]
    assert {type(operation).__name__ for operation in migration.operations} <= {
        "CreateModel",
        "AddConstraint",
        "AddIndex",
    }
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0016_forward_reverse_reforward_is_zero_seed() -> None:
    before = [("research", "0015_r3_macro_factor_runner_spec_ledger")]
    after = [("research", "0016_r2_trial_monitoring_ledgers")]
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        assert not TABLES.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        for model_name in (
            "R2ExplanatoryTrialAssessmentLedgerModel",
            "R2MonitoringObservationLedgerModel",
            "R2MonitoringAssessmentLedgerModel",
            "R2MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        assert not TABLES.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        for model_name in (
            "R2ExplanatoryTrialAssessmentLedgerModel",
            "R2MonitoringObservationLedgerModel",
            "R2MonitoringAssessmentLedgerModel",
            "R2MonitoringAuditSnapshotModel",
        ):
            assert apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0016_constraints_foreign_keys_and_zero_seed_exist() -> None:
    assert TABLES <= set(connection.introspection.table_names())
    expected = {
        TRIAL_TABLE: {
            "res_r2_tm_trial_pit_ix",
            "res_r2_tm_trial_ident_uq",
            "res_r2_tm_trial_status_ck",
            "res_r2_tm_trial_clock_ck",
            "res_r2_tm_trial_safe_ck",
        },
        ASSESSMENT_TABLE: {
            "res_r2_tm_asmt_pit_ix",
            "res_r2_tm_asmt_ident_uq",
            "res_r2_tm_asmt_status_ck",
            "res_r2_tm_asmt_clock_ck",
            "res_r2_tm_asmt_safe_ck",
        },
        OBSERVATION_TABLE: {
            "res_r2_tm_obs_pit_ix",
            "res_r2_tm_obs_scope_uq",
            "res_r2_tm_obs_clock_ck",
            "res_r2_tm_obs_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r2_tm_snap_pit_ix",
            "res_r2_tm_snap_ident_uq",
            "res_r2_tm_snap_clock_ck",
            "res_r2_tm_snap_safe_ck",
        },
    }
    with connection.cursor() as cursor:
        constraints = {
            table: connection.introspection.get_constraints(cursor, table) for table in expected
        }
    for table, names in expected.items():
        assert names <= set(constraints[table])
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
    assessment_targets = {
        details["foreign_key"][0]
        for details in constraints[ASSESSMENT_TABLE].values()
        if details.get("foreign_key")
    }
    assert assessment_targets == {TRIAL_TABLE}
    observation_targets = {
        details["foreign_key"][0]
        for details in constraints[OBSERVATION_TABLE].values()
        if details.get("foreign_key")
    }
    assert observation_targets == {TRIAL_TABLE, ASSESSMENT_TABLE}
