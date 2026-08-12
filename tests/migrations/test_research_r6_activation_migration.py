"""Migration evidence for schema-only R6 activation persistence."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection

AUTHORIZATION_TABLE = "research_r6_activation_authorization"
EVENT_TABLE = "research_r6_activation_event"
COMMIT_TABLE = "research_r6_activation_stream_commit"
SNAPSHOT_TABLE = "research_r6_activation_audit_snapshot"


def test_0012_is_schema_only_and_depends_on_0011() -> None:
    module = importlib.import_module("apps.research.migrations.0012_r6_activation_ledgers")
    migration = module.Migration

    assert migration.dependencies == [("research", "0011_r6_monitoring_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert {operation.name for operation in migration.operations} == {
        "R6ActivationAuthorizationModel",
        "R6ActivationEventModel",
        "R6ActivationStreamCommitModel",
        "R6ActivationAuditSnapshotModel",
    }


@pytest.mark.django_db
def test_0012_tables_constraints_fk_and_zero_seed_exist() -> None:
    assert {AUTHORIZATION_TABLE, EVENT_TABLE, COMMIT_TABLE, SNAPSHOT_TABLE} <= set(
        connection.introspection.table_names()
    )
    expected = {
        AUTHORIZATION_TABLE: {
            "res_r6_act_auth_pit_ix",
            "res_r6_act_auth_ident_uq",
            "res_r6_act_auth_event_uq",
            "res_r6_act_auth_type_ck",
            "res_r6_act_auth_clock_ck",
            "res_r6_act_auth_head_ck",
            "res_r6_act_auth_roll_ck",
            "res_r6_act_auth_safe_ck",
        },
        EVENT_TABLE: {
            "res_r6_act_evt_pit_ix",
            "res_r6_act_evt_ident_uq",
            "res_r6_act_evt_sid_seq_uq",
            "res_r6_act_evt_hash_seq_uq",
            "res_r6_act_evt_type_ck",
            "res_r6_act_evt_clock_ck",
            "res_r6_act_evt_head_ck",
            "res_r6_act_evt_roll_ck",
            "res_r6_act_evt_safe_ck",
        },
        COMMIT_TABLE: {
            "res_r6_act_cmt_pit_ix",
            "res_r6_act_cmt_auth_uq",
            "res_r6_act_cmt_event_uq",
            "res_r6_act_cmt_sid_seq_uq",
            "res_r6_act_cmt_hash_seq_uq",
            "res_r6_act_cmt_head_ck",
            "res_r6_act_cmt_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r6_act_snap_pit_ix",
            "res_r6_act_snap_ident_uq",
            "res_r6_act_snap_clock_ck",
            "res_r6_act_snap_safe_ck",
        },
    }
    with connection.cursor() as cursor:
        constraints_by_table = {
            table: connection.introspection.get_constraints(cursor, table) for table in expected
        }
    for table, names in expected.items():
        assert names <= set(constraints_by_table[table])
    event_targets = {
        details["foreign_key"][0]
        for details in constraints_by_table[EVENT_TABLE].values()
        if details.get("foreign_key")
    }
    assert event_targets == {AUTHORIZATION_TABLE}
    commit_targets = {
        details["foreign_key"][0]
        for details in constraints_by_table[COMMIT_TABLE].values()
        if details.get("foreign_key")
    }
    assert commit_targets == {AUTHORIZATION_TABLE, EVENT_TABLE}
    for table in expected:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)
