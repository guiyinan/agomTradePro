"""Migration coverage for controlled event replay audit persistence."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_event_replay_run_migration_is_reversible() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("events", "0004_event_replay_run")])
        apps = executor.loader.project_state(
            [("events", "0004_event_replay_run")]
        ).apps
        model = apps.get_model("events", "EventReplayRunModel")
        assert model._meta.db_table == "event_replay_run"
        assert any(
            constraint.name == "evt_replay_requester_idem_uniq"
            for constraint in model._meta.constraints
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("events", "0003_add_failed_event_model")])
        assert "event_replay_run" not in connection.introspection.table_names()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
