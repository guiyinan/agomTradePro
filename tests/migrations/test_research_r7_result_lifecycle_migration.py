"""Migration evidence for schema-only R7 result Promotion/retirement ledgers."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection

AUTHORIZATION_TABLE = "research_r7_result_lifecycle_authorization"
EVENT_TABLE = "research_r7_result_lifecycle_event"
SNAPSHOT_TABLE = "research_r7_result_audit_snapshot"


def test_0010_is_schema_only_and_depends_on_final_0009_chain() -> None:
    module = importlib.import_module("apps.research.migrations.0010_r7_result_promotion_lifecycle")
    migration = module.Migration

    assert migration.dependencies == [("research", "0009_r2_market_structure_promotion_ledgers")]
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}


@pytest.mark.django_db
def test_0010_tables_constraints_indexes_and_protected_relations_exist() -> None:
    assert {AUTHORIZATION_TABLE, EVENT_TABLE, SNAPSHOT_TABLE} <= set(
        connection.introspection.table_names()
    )
    expected = {
        AUTHORIZATION_TABLE: {
            "res_r7_lc_auth_pit_ix",
            "res_r7_lc_auth_ident_uq",
            "res_r7_lc_auth_event_uq",
            "res_r7_lc_auth_clock_ck",
            "res_r7_lc_auth_safe_ck",
        },
        EVENT_TABLE: {
            "res_r7_lc_event_pit_ix",
            "res_r7_lc_event_ident_uq",
            "res_r7_lc_event_seq_uq",
            "res_r7_lc_event_clock_ck",
            "res_r7_lc_event_chain_ck",
            "res_r7_lc_event_safe_ck",
        },
        SNAPSHOT_TABLE: {
            "res_r7_audit_snap_pit_ix",
            "res_r7_audit_snap_ident_uq",
            "res_r7_audit_snap_clock_ck",
            "res_r7_audit_snap_safe_ck",
        },
    }
    targets: dict[str, set[str]] = {}
    with connection.cursor() as cursor:
        for table in expected:
            constraints = connection.introspection.get_constraints(cursor, table)
            assert expected[table] <= set(constraints)
            targets[table] = {
                details["foreign_key"][0]
                for details in constraints.values()
                if details.get("foreign_key")
            }
    assert targets[AUTHORIZATION_TABLE] == {"research_r7_research_result"}
    assert targets[EVENT_TABLE] == {
        "research_r7_research_result",
        AUTHORIZATION_TABLE,
    }
    assert targets[SNAPSHOT_TABLE] == set()
