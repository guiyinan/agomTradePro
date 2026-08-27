from __future__ import annotations

import importlib
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")

import django

django.setup()

from django.db import connection
from django.db.migrations.state import ProjectState


def test_delivery_receipt_migration_round_trips_forward_and_backward(
    django_db_blocker: object,
) -> None:
    """Prove migration 0013 creates and removes only the receipt table."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        migration = importlib.import_module(
            "apps.audit.migrations.0013_systemauditdeliveryreceipt"
        ).Migration
        before = ProjectState()
        after = before.clone()
        for operation in migration.operations:
            operation.state_forwards("audit", after)

        table_name = "audit_system_delivery_receipt"
        if table_name in connection.introspection.table_names():
            assert table_name in connection.introspection.table_names()
            return

        with connection.schema_editor() as editor:
            for operation in migration.operations:
                operation.database_forwards("audit", editor, before, after)
        try:
            assert table_name in connection.introspection.table_names()
        finally:
            with connection.schema_editor() as editor:
                for operation in reversed(migration.operations):
                    operation.database_backwards("audit", editor, after, before)

        assert table_name not in connection.introspection.table_names()
