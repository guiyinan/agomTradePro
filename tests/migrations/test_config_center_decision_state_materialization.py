"""Migration evidence for the canonical decision-runtime state."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_decision_state_migration_copies_explicit_legacy_state_and_fails_closed_without_it() -> (
    None
):
    """Upgrades preserve explicit gates while fresh installs start blocked."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("config_center", "0012_qlib_training_run_lock")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [("config_center", "0012_qlib_training_run_lock")]
        ).apps
        Legacy = old_apps.get_model("config_center", "SystemSettingsModel")
        State = old_apps.get_model("config_center", "DecisionRuntimeStateModel")
        State.objects.all().delete()
        Legacy.objects.all().delete()
        changed_at = datetime(2026, 8, 8, 1, 2, tzinfo=UTC)
        Legacy.objects.create(
            id=1,
            decision_runtime_status="maintenance",
            decision_runtime_reason="canonical backfill",
            decision_runtime_changed_at=changed_at,
            decision_runtime_changed_by="migration-test",
            decision_runtime_release_ref="release-1",
        )

        executor.migrate([("config_center", "0013_materialize_decision_runtime_state")])
        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [("config_center", "0013_materialize_decision_runtime_state")]
        ).apps
        State = new_apps.get_model("config_center", "DecisionRuntimeStateModel")
        copied = State.objects.get(pk=1)
        assert copied.status == "maintenance"
        assert copied.reason == "canonical backfill"
        assert copied.changed_at == changed_at
        assert copied.changed_by == "migration-test"
        assert copied.release_ref == "release-1"

        executor.migrate([("config_center", "0012_qlib_training_run_lock")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [("config_center", "0012_qlib_training_run_lock")]
        ).apps
        old_apps.get_model("config_center", "DecisionRuntimeStateModel").objects.all().delete()
        old_apps.get_model("config_center", "SystemSettingsModel").objects.all().delete()

        executor.migrate([("config_center", "0013_materialize_decision_runtime_state")])
        executor = MigrationExecutor(connection)
        fresh_apps = executor.loader.project_state(
            [("config_center", "0013_materialize_decision_runtime_state")]
        ).apps
        seeded = fresh_apps.get_model("config_center", "DecisionRuntimeStateModel").objects.get(
            pk=1
        )
        assert seeded.status == "blocked"
        assert seeded.reason == "决策运行状态尚未初始化。"
        assert seeded.changed_by == "migration:0013"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
