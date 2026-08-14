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


def test_backlog_snapshot_aggregates_recovery_states_without_mutating_rows() -> None:
    repository = _repository()
    pending_event = make_event(event_id="evt-pending", idempotency_key="fetch:pending")
    claimed_event = make_event(event_id="evt-claimed", idempotency_key="fetch:claimed")
    failed_event = make_event(event_id="evt-failed", idempotency_key="fetch:failed")
    delivered_event = make_event(event_id="evt-delivered", idempotency_key="fetch:delivered")

    with repository.atomic():
        repository.enqueue(
            pending_event,
            created_at=NOW + timedelta(seconds=4),
            available_at=NOW + timedelta(hours=1),
        )
        failed_record = repository.enqueue(
            failed_event,
            created_at=NOW + timedelta(seconds=2),
            available_at=NOW + timedelta(seconds=2),
        )
        failed_claim = repository.claim_due(worker_id="worker-failed", as_of=LATER, limit=1)[0]
        assert failed_claim.outbox_id == failed_record.outbox_id
        repository.mark_failed(
            outbox_id=failed_claim.outbox_id,
            worker_id=failed_claim.worker_id,
            claim_token=failed_claim.claim_token,
            error_code="publisher_error",
            failed_at=LATER,
        )

    with repository.atomic():
        repository.enqueue(
            claimed_event,
            created_at=NOW + timedelta(seconds=1),
            available_at=NOW + timedelta(seconds=1),
        )
        claimed = repository.claim_due(worker_id="worker-claimed", as_of=LATER, limit=1)[0]
        assert claimed.event == claimed_event

    with repository.atomic():
        delivered_record = repository.enqueue(
            delivered_event,
            created_at=NOW + timedelta(seconds=3),
            available_at=NOW + timedelta(seconds=3),
        )
        delivered_claim = repository.claim_due(worker_id="worker-delivered", as_of=LATER, limit=1)[
            0
        ]
        assert delivered_claim.outbox_id == delivered_record.outbox_id
        repository.mark_delivered(
            outbox_id=delivered_claim.outbox_id,
            worker_id=delivered_claim.worker_id,
            claim_token=delivered_claim.claim_token,
            delivered_at=LATER,
        )

    snapshot = repository.get_backlog_snapshot(as_of=LATER)

    assert snapshot.pending_count == 1
    assert snapshot.due_pending_count == 0
    assert snapshot.claimed_count == 1
    assert snapshot.expired_claimed_count == 0
    assert snapshot.failed_count == 1
    assert snapshot.delivered_count == 1
    assert snapshot.backlog_count == 2
    assert snapshot.oldest_backlog_at == NOW + timedelta(seconds=1)
    assert snapshot.oldest_claimed_at == LATER
    assert snapshot.oldest_backlog_age_seconds == pytest.approx(59.0)
    assert snapshot.oldest_claimed_age_seconds == pytest.approx(0.0)
    assert repository.get_exact(outbox_id=failed_record.outbox_id) is not None


def test_backlog_snapshot_marks_expired_claims_without_reclaiming_them() -> None:
    repository = _repository()
    event = make_event(event_id="evt-expired", idempotency_key="fetch:expired")
    with repository.atomic():
        record = repository.enqueue(event, created_at=NOW, available_at=NOW)
        claim = repository.claim_due(worker_id="worker-1", as_of=LATER, limit=1)[0]

    observed = repository.get_backlog_snapshot(as_of=LATER + timedelta(minutes=5))

    assert observed.claimed_count == 1
    assert observed.expired_claimed_count == 1
    restored = repository.get_exact(outbox_id=record.outbox_id)
    assert restored is not None
    assert restored.claim_token == claim.claim_token
    assert restored.status == SystemAuditOutboxModel.STATUS_CLAIMED
