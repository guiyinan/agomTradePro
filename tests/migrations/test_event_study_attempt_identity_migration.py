"""SQLite must keep the original binding guards when reversing research 0031."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_reversing_attempt_identity_restores_the_binding_guards() -> None:
    if connection.vendor != "sqlite":
        pytest.skip("SQLite rebuilds the binding table when removing its unique constraint")
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    before_binding = [("research", "0029_evidence_scope_source_v1_observation_ledger")]
    binding = [("research", "0030_event_study_final_oos_control")]
    attempt = [("research", "0031_event_study_attempt_identity")]

    def assert_binding_guards() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='research_event_study_binding'"
            )
            guards = dict(cursor.fetchall())
        for action in ("UPDATE", "DELETE"):
            sql = guards[f"research_event_study_binding_immutable_{action.lower()}"]
            assert f"BEFORE {action} ON research_event_study_binding" in sql
            assert "RAISE(ABORT, 'Event-study evidence is immutable')" in sql

    try:
        MigrationExecutor(connection).migrate(before_binding)
        for target in (binding, attempt, binding):
            MigrationExecutor(connection).migrate(target)
            assert_binding_guards()
        MigrationExecutor(connection).migrate(before_binding)
        assert "research_event_study_binding" not in connection.introspection.table_names()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
