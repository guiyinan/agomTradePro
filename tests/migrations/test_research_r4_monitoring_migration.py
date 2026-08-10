"""Migration evidence for schema-only R4 monitoring persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection

OBSERVATION_TABLE = "research_r4_monitoring_observation"
ASSESSMENT_TABLE = "research_r4_monitoring_assessment"
SNAPSHOT_TABLE = "research_r4_monitoring_audit_snapshot"
DECISION_TABLE = "research_r4_promotion_decision_bundle"


def test_0013_is_schema_only_and_depends_on_0012() -> None:
    module = importlib.import_module("apps.research.migrations.0013_r4_monitoring_ledgers")
    migration = module.Migration

    assert migration.dependencies == [("research", "0012_r6_activation_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert {operation.name for operation in migration.operations} == {
        "R4MonitoringObservationLedgerModel",
        "R4MonitoringAssessmentLedgerModel",
        "R4MonitoringAuditSnapshotModel",
    }


@pytest.mark.django_db
def test_0013_tables_constraints_fk_and_zero_seed_exist() -> None:
    assert {OBSERVATION_TABLE, ASSESSMENT_TABLE, SNAPSHOT_TABLE} <= set(
        connection.introspection.table_names()
    )
    expected = {
        OBSERVATION_TABLE: {
            "res_r4_mon_obs_pit_ix",
            "res_r4_mon_obs_ident_uq",
            "res_r4_mon_obs_period_uq",
            "res_r4_mon_obs_clock_ck",
            "res_r4_mon_obs_safe_ck",
        },
        ASSESSMENT_TABLE: {
            "res_r4_mon_asmt_pit_ix",
            "res_r4_mon_asmt_cmd_uq",
            "res_r4_mon_asmt_clock_ck",
            "res_r4_mon_asmt_status_ck",
            "res_r4_mon_asmt_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r4_mon_snap_pit_ix",
            "res_r4_mon_snap_ident_uq",
            "res_r4_mon_snap_clock_ck",
            "res_r4_mon_snap_safe_ck",
        },
    }
    with connection.cursor() as cursor:
        constraints = {
            table: connection.introspection.get_constraints(cursor, table) for table in expected
        }
    for table, names in expected.items():
        assert names <= set(constraints[table])
    for table in (OBSERVATION_TABLE, ASSESSMENT_TABLE):
        targets = {
            details["foreign_key"][0]
            for details in constraints[table].values()
            if details.get("foreign_key")
        }
        assert targets == {DECISION_TABLE}
    for table in expected:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
