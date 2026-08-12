"""Migration evidence for schema-only Data Center R3 source ledgers."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

SOURCE_TABLE = "data_center_macro_factor_source"
PERIOD_TABLE = "data_center_macro_factor_calendar_period"
MEMBER_TABLE = "data_center_macro_factor_member_rule"
TABLES = {SOURCE_TABLE, PERIOD_TABLE, MEMBER_TABLE}
BEFORE = [("data_center", "0068_evaluation_actual_ledgers")]
AFTER = [("data_center", "0069_macro_factor_research_source")]


def test_0069_is_schema_only_and_has_the_exact_0068_dependency() -> None:
    module = importlib.import_module(
        "apps.data_center.migrations.0069_macro_factor_research_source"
    )
    migration = module.Migration

    assert migration.dependencies == BEFORE
    assert len(migration.operations) == 3
    assert {type(operation).__name__ for operation in migration.operations} == {"CreateModel"}
    assert not any(
        type(operation).__name__ in {"RunPython", "RunSQL"} for operation in migration.operations
    )


@pytest.mark.django_db(transaction=True)
def test_0069_forward_reverse_reforward_is_zero_seed() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(BEFORE)
        assert TABLES.isdisjoint(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        source = apps.get_model("data_center", "MacroFactorResearchSourceDefinitionModel")
        period = apps.get_model("data_center", "MacroFactorResearchCalendarPeriodModel")
        member = apps.get_model("data_center", "MacroFactorResearchMemberRuleModel")
        assert source.objects.count() == 0
        assert period.objects.count() == 0
        assert member.objects.count() == 0

        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        assert TABLES.isdisjoint(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        apps = executor.loader.project_state(AFTER).apps
        source = apps.get_model("data_center", "MacroFactorResearchSourceDefinitionModel")
        period = apps.get_model("data_center", "MacroFactorResearchCalendarPeriodModel")
        member = apps.get_model("data_center", "MacroFactorResearchMemberRuleModel")
        assert source.objects.count() == 0
        assert period.objects.count() == 0
        assert member.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0069_tables_constraints_indexes_and_protected_graph_exist() -> None:
    assert TABLES <= set(connection.introspection.table_names())
    expected = {
        SOURCE_TABLE: {
            "dc_mfsrc_identity_uq",
            "dc_mfsrc_sem_ck",
            "dc_mfsrc_safe_ck",
            "dc_mfsrc_pit_idx",
        },
        PERIOD_TABLE: {
            "dc_mfsrc_period_row_uq",
            "dc_mfsrc_period_id_uq",
            "dc_mfsrc_period_sem_ck",
        },
        MEMBER_TABLE: {
            "dc_mfsrc_member_sem_uq",
            "dc_mfsrc_member_fact_uq",
            "dc_mfsrc_member_sem_ck",
            "dc_mfsrc_member_row_idx",
        },
    }
    constraints_by_table: dict[str, dict[str, object]] = {}
    with connection.cursor() as cursor:
        for table, names in expected.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            constraints_by_table[table] = constraints
            assert names <= set(constraints)
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)

    period_targets = {
        details["foreign_key"][0]
        for details in constraints_by_table[PERIOD_TABLE].values()
        if details.get("foreign_key")
    }
    member_targets = {
        details["foreign_key"][0]
        for details in constraints_by_table[MEMBER_TABLE].values()
        if details.get("foreign_key")
    }
    assert period_targets == {SOURCE_TABLE}
    assert member_targets == {SOURCE_TABLE, PERIOD_TABLE}
