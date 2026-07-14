"""Migration tests for semantic governance persistence."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_semantic_governance_migration_backfills_collected_key() -> None:
    """Existing effective keys become the initial collected-key evidence."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("ai_capability", "0004_capabilitycatalogmodel_semantic_key")])
        old_apps = executor.loader.project_state(
            [("ai_capability", "0004_capabilitycatalogmodel_semantic_key")]
        ).apps
        old_catalog = old_apps.get_model(
            "ai_capability",
            "CapabilityCatalogModel",
        )
        old_catalog.objects.create(
            capability_key="mcp_tool.replay_events",
            source_type="mcp_tool",
            source_ref="replay_events",
            name="replay_events",
            summary="Replay events",
            semantic_key="legacy.mcp.replay_events",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("ai_capability", "0005_semantic_governance")])
        new_apps = executor.loader.project_state(
            [("ai_capability", "0005_semantic_governance")]
        ).apps
        new_catalog = new_apps.get_model(
            "ai_capability",
            "CapabilityCatalogModel",
        )
        migrated = new_catalog.objects.get(
            capability_key="mcp_tool.replay_events"
        )

        assert migrated.collected_semantic_key == "legacy.mcp.replay_events"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
