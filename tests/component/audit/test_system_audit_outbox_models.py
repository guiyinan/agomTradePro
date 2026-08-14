from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")
django.setup()

from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.infrastructure.system_audit_outbox_models import (
    SystemAuditOutboxModel,
    _activate_system_audit_outbox_uow,
    _claim_system_audit_outbox_insert,
)

NOW = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> None:
    blocker = django_db_blocker
    with blocker.unblock():  # type: ignore[attr-defined]
        table_name = SystemAuditOutboxModel._meta.db_table
        created = table_name not in connection.introspection.table_names()
        if created:
            with connection.schema_editor() as editor:
                editor.create_model(SystemAuditOutboxModel)
        yield
        if created:
            with connection.schema_editor() as editor:
                editor.delete_model(SystemAuditOutboxModel)


def _row(*, payload: dict[str, object] | None = None) -> SystemAuditOutboxModel:
    return SystemAuditOutboxModel(
        outbox_id=uuid4(),
        event_id="event-1",
        idempotency_key="event-1-attempt",
        payload=payload or {"event_id": "event-1", "content_hash": "a" * 64},
        payload_hash="a" * 64,
        available_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _insert(row: SystemAuditOutboxModel) -> SystemAuditOutboxModel:
    values = {
        field.name: getattr(row, field.name) for field in SystemAuditOutboxModel._meta.fields
    }
    token = object()
    with _activate_system_audit_outbox_uow(token):
        with _claim_system_audit_outbox_insert(
            token=token,
            model_type=SystemAuditOutboxModel,
            expected_values=values,
        ):
            row.save(force_insert=True)
    return row


def test_schema_is_zero_seeded_and_contains_claim_state() -> None:
    assert SystemAuditOutboxModel.objects.count() == 0
    fields = {field.name for field in SystemAuditOutboxModel._meta.fields}
    assert {
        "outbox_id",
        "event_id",
        "idempotency_key",
        "payload",
        "payload_hash",
        "status",
        "attempt_count",
        "available_at",
        "claimed_at",
        "claimed_by",
        "updated_at",
    } <= fields


def test_payload_identity_and_delete_are_guarded_but_claim_state_can_change() -> None:
    row = _row()
    with pytest.raises(ValidationError, match="exact private claim"):
        row.save()
    _insert(row)

    row.payload = {"event_id": "event-1", "content_hash": "b" * 64}
    with pytest.raises(ValidationError, match="immutable"):
        row.save()
    with pytest.raises(ValidationError, match="immutable"):
        SystemAuditOutboxModel.objects.filter(pk=row.pk).update(payload={"tampered": True})

    claimed_at = NOW + timedelta(seconds=1)
    row.status = SystemAuditOutboxModel.STATUS_CLAIMED
    row.claimed_at = claimed_at
    row.claimed_by = "dispatcher-1"
    row.updated_at = claimed_at
    row.save(update_fields=["status", "claimed_at", "claimed_by", "updated_at"])
    assert SystemAuditOutboxModel.objects.get(pk=row.pk).status == "claimed"

    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        SystemAuditOutboxModel.objects.filter(pk=row.pk).delete()


def test_migration_is_two_create_models_without_data_operations() -> None:
    module = importlib.import_module("apps.audit.migrations.0011_systemauditeventmodel")
    assert [type(operation).__name__ for operation in module.Migration.operations] == [
        "CreateModel",
        "CreateModel",
    ]
    assert module.Migration.dependencies == [("audit", "0010_alter_attribution_regime_actual")]
