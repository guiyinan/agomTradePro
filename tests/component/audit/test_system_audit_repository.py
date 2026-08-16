from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_event")

import django

django.setup()

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_repository import (
    DjangoSystemAuditEventRepository,
    SystemAuditConflict,
    SystemAuditCorruption,
    SystemAuditUnavailable,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)


class FixedClock:
    """Deterministic aware clock for SQLite component evidence."""

    def now(self) -> datetime:
        return NOW + timedelta(days=1)


@pytest.fixture(scope="module", autouse=True)
def _audit_event_table(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((SystemAuditEventModel,)):
            yield


@pytest.fixture(autouse=True)
def _clear_audit_events(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_system_event")
        yield


def _repository() -> DjangoSystemAuditEventRepository:
    return DjangoSystemAuditEventRepository(clock=FixedClock())


def _successor(
    root: SystemAuditEvent, *, detail: dict[str, object] | None = None
) -> SystemAuditEvent:
    return SystemAuditEvent.create(
        event_id=root.event_id,
        event_version="2",
        schema_version=root.schema_version,
        category=root.category,
        event_type=root.event_type,
        owner=root.owner,
        write_policy=root.write_policy,
        outcome=root.outcome,
        severity=root.severity,
        reason_codes=root.reason_codes,
        occurred_at=root.occurred_at,
        recorded_at=LATER,
        observed_at=root.observed_at,
        actor=root.actor,
        source_app=root.source_app,
        source_component=root.source_component,
        source_surface=root.source_surface,
        correlations=root.correlations,
        resource=root.resource,
        dataset_key=root.dataset_key,
        provider_key=root.provider_key,
        capability=root.capability,
        publication_id=root.publication_id,
        evidence_refs=root.evidence_refs,
        scope=root.scope,
        detail_schema=root.detail_schema,
        detail=detail if detail is not None else dict(root.detail),
        stream_id=root.stream_id,
        sequence_no=2,
        predecessor_hash=root.content_hash,
        idempotency_key="fetch:run-1:successor",
    )


def _different_identity_payload(root: SystemAuditEvent) -> SystemAuditEvent:
    return SystemAuditEvent.create(
        event_id=root.event_id,
        event_version=root.event_version,
        schema_version=root.schema_version,
        category=root.category,
        event_type=root.event_type,
        owner=root.owner,
        write_policy=root.write_policy,
        outcome=root.outcome,
        severity=root.severity,
        reason_codes=root.reason_codes,
        occurred_at=root.occurred_at,
        recorded_at=root.recorded_at,
        observed_at=root.observed_at,
        actor=root.actor,
        source_app=root.source_app,
        source_component=root.source_component,
        source_surface=root.source_surface,
        correlations=root.correlations,
        resource=root.resource,
        dataset_key=root.dataset_key,
        provider_key=root.provider_key,
        capability=root.capability,
        publication_id=root.publication_id,
        evidence_refs=root.evidence_refs,
        scope=root.scope,
        detail_schema=root.detail_schema,
        detail={"rows": 3, "source_status": "valid", "nested": {"ok": True}},
        stream_id=root.stream_id,
        sequence_no=root.sequence_no,
        predecessor_hash=root.predecessor_hash,
        idempotency_key=root.idempotency_key,
    )


def test_root_append_exact_replay_and_pit_reads() -> None:
    repository = _repository()
    root = make_event()
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )
            == root
        )
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=NOW,
            )
            == root
        )
    assert SystemAuditEventModel._default_manager.count() == 1
    assert (
        repository.get_exact_by_hash(
            event_id=root.event_id,
            event_version=root.event_version,
            expected_content_hash=root.content_hash,
            as_of=NOW,
        )
        == root
    )
    assert repository.get_current_head(stream_id=root.stream_id, as_of=NOW) == root


def test_successor_cas_and_pit_head_never_fallback_from_future_state() -> None:
    repository = _repository()
    root = make_event()
    successor = _successor(root)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(SystemAuditConflict, match="predecessor CAS"):
            repository.append(
                successor,
                expected_predecessor_hash="b" * 64,
                recorded_at=LATER,
            )
    assert (
        repository.get_current_head(stream_id=root.stream_id, as_of=NOW + timedelta(seconds=30))
        == root
    )
    with repository.atomic():
        repository.append(
            successor,
            expected_predecessor_hash=root.content_hash,
            recorded_at=LATER,
        )
    assert repository.get_current_head(stream_id=root.stream_id, as_of=NOW) == root
    assert repository.get_current_head(stream_id=root.stream_id, as_of=LATER) == successor
    assert repository.list_events(stream_id=root.stream_id, as_of=LATER) == (root, successor)


def test_same_identity_different_content_is_conflict_and_append_requires_uow() -> None:
    repository = _repository()
    root = make_event()
    different = _different_identity_payload(root)
    with pytest.raises(SystemAuditConflict, match="repository.atomic"):
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(SystemAuditConflict, match="another winner"):
            repository.append(different, expected_predecessor_hash=None, recorded_at=NOW)
    with pytest.raises(ValidationError, match="may not be nested"):
        with repository.atomic():
            with repository.atomic():
                pass


def test_unrelated_scalar_tamper_is_hidden_by_no_selector_and_fails_closed() -> None:
    repository = _repository()
    root = make_event()
    with repository.atomic():
        repository.append(root, expected_predecessor_hash=None, recorded_at=NOW)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_system_event SET owner = %s WHERE event_id = %s",
            ["tampered", root.event_id],
        )
    with pytest.raises(SystemAuditCorruption, match="headers"):
        repository.get_current_head(stream_id=root.stream_id, as_of=NOW)


def test_future_recorded_at_append_is_rejected() -> None:
    repository = _repository()
    root = make_event()
    future = _successor(root)
    future = replace(future, recorded_at=NOW + timedelta(days=2))
    with repository.atomic():
        with pytest.raises(SystemAuditUnavailable, match="future"):
            repository.append(
                future,
                expected_predecessor_hash=None,
                recorded_at=future.recorded_at,
            )
