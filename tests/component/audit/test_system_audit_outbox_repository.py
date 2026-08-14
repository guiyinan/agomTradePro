from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_audit_system_event")

import django

django.setup()

import pytest
from django.db import connection

from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
    SystemAuditOutboxConflict,
    SystemAuditOutboxCorruption,
)
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)


class FixedClock:
    """Deterministic aware clock for SQLite structural evidence."""

    def now(self) -> datetime:
        return NOW + timedelta(days=1)


@pytest.fixture(scope="module", autouse=True)
def _outbox_table(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.schema_editor() as editor:
            editor.create_model(SystemAuditOutboxModel)
        yield
        with connection.schema_editor() as editor:
            editor.delete_model(SystemAuditOutboxModel)


@pytest.fixture(autouse=True)
def _clear_outbox(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_system_outbox")
        yield


def _repository() -> DjangoSystemAuditOutboxRepository:
    return DjangoSystemAuditOutboxRepository(clock=FixedClock())


def test_enqueue_claim_deliver_and_exact_replay() -> None:
    repository = _repository()
    event = make_event()
    with repository.atomic():
        first = repository.enqueue(event, created_at=NOW, available_at=NOW)
    with repository.atomic():
        replay = repository.enqueue(event, created_at=NOW, available_at=NOW)
    assert replay == first
    with repository.atomic():
        claims = repository.claim_due(worker_id="worker-1", as_of=LATER, limit=10)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.outbox_id == UUID(str(first.outbox_id))
    with repository.atomic():
        delivered = repository.mark_delivered(
            outbox_id=claim.outbox_id,
            worker_id=claim.worker_id,
            claim_token=claim.claim_token,
            delivered_at=LATER,
        )
    assert delivered.status == SystemAuditOutboxModel.STATUS_DELIVERED
    assert repository.get_exact(outbox_id=claim.outbox_id) == delivered


def test_claim_token_and_state_transitions_fail_closed() -> None:
    repository = _repository()
    event = make_event()
    with repository.atomic():
        record = repository.enqueue(event, created_at=NOW, available_at=NOW)
        claim = repository.claim_due(worker_id="worker-1", as_of=LATER, limit=1)[0]
        with pytest.raises(SystemAuditOutboxConflict, match="token"):
            repository.mark_delivered(
                outbox_id=claim.outbox_id,
                worker_id="other-worker",
                claim_token=claim.claim_token,
                delivered_at=LATER,
            )
        failed = repository.mark_failed(
            outbox_id=claim.outbox_id,
            worker_id="worker-1",
            claim_token=claim.claim_token,
            error_code="publisher_error",
            failed_at=LATER,
        )
    assert failed.status == SystemAuditOutboxModel.STATUS_FAILED
    assert failed.last_error_code == "publisher_error"
    assert record.status == SystemAuditOutboxModel.STATUS_PENDING


def test_expired_claim_is_reclaimed_with_new_token_and_attempt() -> None:
    repository = _repository()
    event = make_event()
    with repository.atomic():
        repository.enqueue(event, created_at=NOW, available_at=NOW)
        first_claim = repository.claim_due(worker_id="worker-1", as_of=LATER, limit=1)[0]

    lease_expiry = LATER + timedelta(minutes=5)
    with repository.atomic():
        assert (
            repository.claim_due(
                worker_id="worker-2",
                as_of=lease_expiry - timedelta(seconds=1),
                limit=1,
            )
            == ()
        )
        reclaimed = repository.claim_due(
            worker_id="worker-2",
            as_of=lease_expiry,
            limit=1,
        )[0]
        assert reclaimed.outbox_id == first_claim.outbox_id
        assert reclaimed.claim_token != first_claim.claim_token
        assert reclaimed.attempt_count == first_claim.attempt_count + 1
        with pytest.raises(SystemAuditOutboxConflict, match="token"):
            repository.mark_delivered(
                outbox_id=first_claim.outbox_id,
                worker_id=first_claim.worker_id,
                claim_token=first_claim.claim_token,
                delivered_at=lease_expiry,
            )
        delivered = repository.mark_delivered(
            outbox_id=reclaimed.outbox_id,
            worker_id=reclaimed.worker_id,
            claim_token=reclaimed.claim_token,
            delivered_at=lease_expiry,
        )
    assert delivered.status == SystemAuditOutboxModel.STATUS_DELIVERED
    assert delivered.attempt_count == 2


def test_full_table_restore_rejects_payload_tamper() -> None:
    repository = _repository()
    event = make_event()
    with repository.atomic():
        record = repository.enqueue(event, created_at=NOW, available_at=NOW)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_system_outbox SET payload = %s WHERE outbox_id = %s",
            ['{"event_id":"tampered"}', record.outbox_id.hex],
        )
    with pytest.raises(SystemAuditOutboxCorruption, match="canonical payload"):
        repository.get_exact(outbox_id=record.outbox_id)


def test_private_uow_and_invalid_claim_limit_are_enforced() -> None:
    repository = _repository()
    with pytest.raises(SystemAuditOutboxConflict, match="atomic"):
        repository.enqueue(make_event())
    with repository.atomic():
        repository.enqueue(make_event(), created_at=NOW, available_at=NOW)
        with pytest.raises(SystemAuditOutboxConflict, match="limit"):
            repository.claim_due(worker_id="worker-1", as_of=LATER, limit=0)
        with pytest.raises(SystemAuditOutboxConflict, match="nested"):
            with repository.atomic():
                pass
