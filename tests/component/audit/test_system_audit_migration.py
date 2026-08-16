from __future__ import annotations

import importlib
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")

import django

django.setup()

from django.db import connection
from django.db.migrations.state import ProjectState


def test_system_audit_migration_round_trips_forward_and_backward(
    django_db_blocker: object,
) -> None:
    """Validate migration 0011 without replaying it over an already migrated DB."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        migration = importlib.import_module(
            "apps.audit.migrations.0011_systemauditeventmodel"
        ).Migration
        before = ProjectState()
        after = before.clone()
        for operation in migration.operations:
            operation.state_forwards("audit", after)

        table_names = {
            "audit_system_event",
            "audit_system_outbox",
        }
        existing_tables = set(connection.introspection.table_names())
        if table_names & existing_tables:
            # The full component suite has already applied this migration.
            # Re-running database_forwards would be a duplicate-table operation;
            # the deployed schema is the authoritative check in that mode.
            assert table_names <= existing_tables
            return

        with connection.schema_editor() as editor:
            for operation in migration.operations:
                operation.database_forwards("audit", editor, before, after)
        try:
            assert table_names <= set(connection.introspection.table_names())
        finally:
            with connection.schema_editor() as editor:
                for operation in reversed(migration.operations):
                    operation.database_backwards("audit", editor, after, before)

        assert table_names.isdisjoint(connection.introspection.table_names())
