from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_event")

import django

django.setup()

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_codec import encode
from apps.audit.infrastructure.system_audit_models import (
    SystemAuditEventModel,
    _activate_system_audit_uow,
    _claim_system_audit_insert,
)
from tests.unit.audit.test_system_audit_event import make_event


@pytest.fixture(scope="module", autouse=True)
def _audit_event_table(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.schema_editor() as editor:
            editor.create_model(SystemAuditEventModel)
        yield
        with connection.schema_editor() as editor:
            editor.delete_model(SystemAuditEventModel)


@pytest.fixture(autouse=True)
def _clear_audit_events(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_system_event")
        yield


def _row(event: SystemAuditEvent) -> SystemAuditEventModel:
    payload = encode(event)
    return SystemAuditEventModel(
        event_id=event.event_id,
        event_version=event.event_version,
        schema_version=event.schema_version,
        category=event.category.value,
        event_type=event.event_type,
        owner=event.owner,
        scope_tenant_id=event.scope.tenant_id if event.scope is not None else None,
        scope_owner_id=event.scope.owner_id if event.scope is not None else None,
        write_policy=event.write_policy.value,
        outcome=event.outcome.value,
        severity=event.severity.value,
        reason_codes=list(event.reason_codes),
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        observed_at=event.observed_at,
        actor_type=event.actor.actor_type,
        actor_id=event.actor.actor_id,
        actor_display=event.actor.actor_display,
        source_app=event.source_app,
        source_component=event.source_component,
        source_surface=event.source_surface,
        correlations=dict(event.correlations.to_payload()),
        resource_type=event.resource.resource_type if event.resource else None,
        resource_id=event.resource.resource_id if event.resource else None,
        resource_version=event.resource.resource_version if event.resource else None,
        dataset_key=event.dataset_key,
        provider_key=event.provider_key,
        capability=event.capability,
        publication_id=event.publication_id,
        evidence_refs=[dict(ref.to_payload()) for ref in event.evidence_refs],
        detail_schema=event.detail_schema,
        detail=dict(event.detail),
        canonical_payload=dict(payload),
        stream_id=event.stream_id,
        sequence_no=event.sequence_no,
        predecessor_hash=event.predecessor_hash,
        idempotency_key=event.idempotency_key,
        identity_hash=event.identity_hash,
        content_hash=event.content_hash,
        persisted_at=event.recorded_at,
    )


def test_schema_is_zero_seeded_and_exact_claim_is_required() -> None:
    assert SystemAuditEventModel._default_manager.count() == 0
    event = make_event()
    row = _row(event)
    with pytest.raises(ValidationError, match="private claim"):
        row.save()
    with _activate_system_audit_uow():
        with _claim_system_audit_insert(event.event_id, event.content_hash):
            row.save()
    assert SystemAuditEventModel._default_manager.count() == 1


def test_append_only_guards_cover_instance_and_queryset_paths() -> None:
    event = make_event()
    with _activate_system_audit_uow():
        with _claim_system_audit_insert(event.event_id, event.content_hash):
            row = _row(event)
            row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        SystemAuditEventModel._default_manager.filter(pk=row.pk).update(owner="other")
    with pytest.raises(ValidationError, match="append-only"):
        SystemAuditEventModel._default_manager.filter(pk=row.pk).delete()


def test_duplicate_identity_and_stream_sequence_are_database_unique() -> None:
    event = make_event()
    with _activate_system_audit_uow():
        with _claim_system_audit_insert(event.event_id, event.content_hash):
            _row(event).save()
    duplicate = make_event()
    with _activate_system_audit_uow():
        with _claim_system_audit_insert(duplicate.event_id, duplicate.content_hash):
            with pytest.raises(IntegrityError):
                _row(duplicate).save()
