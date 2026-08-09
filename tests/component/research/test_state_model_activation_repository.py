"""Component tests for the append-only R6 activation persistence boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector, ProtectedError
from django.test import override_settings

from apps.research.application.state_model_activation import (
    R6ActivationConflict,
    R6ActivationCorruption,
)
from apps.research.application.state_model_activation_persistence import (
    AuditR6ActivationEventsCommand,
    R6ActivationEventRef,
)
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationEvent,
    R6ActivationScopeRef,
    create_r6_activation_event,
)
from apps.research.infrastructure.state_model_activation_models import (
    R6ActivationAuditSnapshotModel,
    R6ActivationAuthorizationModel,
    R6ActivationEventModel,
    R6ActivationStreamCommitModel,
)
from apps.research.infrastructure.state_model_activation_repository import (
    _DjangoR6ActivationStore,
)

BASE = datetime(2026, 8, 9, 1, tzinfo=UTC)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class WideInt(int):
    """Comparison-overriding integer used to attack range checks."""

    def __lt__(self, other: object) -> bool:
        return False

    def __gt__(self, other: object) -> bool:
        return False


def _transition(
    number: int,
    history: tuple[R6ActivationEvent, ...],
    *,
    action: R6ActivationAction = R6ActivationAction.ACTIVATE,
) -> tuple[R6ActivationAuthorization, R6ActivationEvent]:
    instant = BASE + timedelta(seconds=number * 10)
    active_subject = (
        R6ActivationApprovalRef("approval-1", "v1", "b" * 64)
        if action is R6ActivationAction.RETIRE
        else R6ActivationApprovalRef(f"approval-{number}", "v1", f"{number}" * 64)
    )
    authorization = R6ActivationAuthorization(
        authorization_id=f"authorization-{number}",
        authorization_version="v1",
        event_id=f"event-{number}",
        event_version="v1",
        scope_ref=R6ActivationScopeRef("scope-1", "v1", "a" * 64),
        action=action,
        subject=active_subject,
        rollback_target=None,
        expected_sequence=number,
        expected_previous_event_hash=None if not history else history[-1].content_hash,
        owner="research",
        issued_at=instant,
        recorded_at=instant + timedelta(seconds=1),
        valid_until=instant + timedelta(hours=1),
        reason_codes=("manual-approval",),
        evidence_ref=f"research://activation/authorization-{number}",
    )
    event = create_r6_activation_event(
        authorization=authorization,
        previous_events=history,
        applied_at=instant + timedelta(seconds=2),
    )
    return authorization, event


def _append(
    store: _DjangoR6ActivationStore,
    authorization: R6ActivationAuthorization,
    event: R6ActivationEvent,
    *,
    ledger_recorded_at: datetime | None = None,
) -> R6ActivationEvent:
    if isinstance(store._clock, FixedClock):
        store._clock.value = ledger_recorded_at or event.recorded_at
    with store.atomic():
        return store.append_event(authorization=authorization, event=event)


@pytest.mark.django_db(transaction=True)
def test_activation_repository_round_trip_exact_pit_and_idempotency() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization, event = _transition(1, ())

    assert _append(store, authorization, event) == event
    assert _append(store, authorization, event) == event
    assert R6ActivationAuthorizationModel._default_manager.count() == 1
    assert R6ActivationEventModel._default_manager.count() == 1
    assert R6ActivationStreamCommitModel._default_manager.count() == 1

    before = event.recorded_at - timedelta(microseconds=1)
    assert (
        repository.get_exact_event(
            event_ref=R6ActivationEventRef(
                event.event_id,
                event.event_version,
                event.content_hash,
            ),
            as_of=before,
        )
        is None
    )
    assert (
        repository.get_exact_authorization(
            authorization_ref=authorization.ref,
            expected_hash=authorization.content_hash,
            as_of=before,
        )
        is None
    )
    assert (
        repository.get_exact_event(
            event_ref=R6ActivationEventRef(
                event.event_id,
                event.event_version,
                event.content_hash,
            ),
            as_of=clock.value,
        )
        == event
    )
    assert (
        repository.get_exact_authorization(
            authorization_ref=authorization.ref,
            expected_hash=authorization.content_hash,
            as_of=clock.value,
        )
        == authorization
    )


@pytest.mark.django_db(transaction=True)
def test_activation_append_rejects_fork_and_outer_rollback_is_atomic() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    authorization, event = _transition(1, ())
    with pytest.raises(RuntimeError, match="rollback"):
        with store.atomic():
            store.append_event(authorization=authorization, event=event)
            raise RuntimeError("rollback")
    assert R6ActivationAuthorizationModel._default_manager.count() == 0
    assert R6ActivationEventModel._default_manager.count() == 0
    assert R6ActivationStreamCommitModel._default_manager.count() == 0

    _append(store, authorization, event)
    fork_authorization = R6ActivationAuthorization(
        authorization_id="fork-authorization",
        authorization_version="v1",
        event_id="fork-event",
        event_version="v1",
        scope_ref=authorization.scope_ref,
        action=R6ActivationAction.ACTIVATE,
        subject=R6ActivationApprovalRef("fork-approval", "v1", "c" * 64),
        rollback_target=None,
        expected_sequence=1,
        expected_previous_event_hash=None,
        owner="research",
        issued_at=authorization.issued_at,
        recorded_at=authorization.recorded_at,
        valid_until=authorization.valid_until,
        reason_codes=("manual-approval",),
        evidence_ref="research://activation/fork",
    )
    fork_event = create_r6_activation_event(
        authorization=fork_authorization,
        previous_events=(),
        applied_at=event.recorded_at,
    )
    with pytest.raises(R6ActivationConflict):
        _append(store, fork_authorization, fork_event)
    assert R6ActivationEventModel._default_manager.count() == 1
    assert R6ActivationStreamCommitModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_activation_audit_snapshot_is_signed_and_excludes_later_backdated_append() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)
    as_of = BASE + timedelta(hours=1)
    clock.value = BASE + timedelta(days=1)

    first = repository.list_audit(as_of=as_of, cursor=None, limit=1)
    assert tuple(item.event_ref.event_id for item in first.entries) == ("event-1",)
    assert first.next_cursor is not None
    assert R6ActivationAuditSnapshotModel._default_manager.count() == 1

    authorization_3, event_3 = _transition(3, (event_1, event_2))
    _append(store, authorization_3, event_3)
    clock.value = BASE + timedelta(days=1)
    second = repository.list_audit(as_of=as_of, cursor=first.next_cursor, limit=1)
    assert tuple(item.event_ref.event_id for item in second.entries) == ("event-2",)
    assert second.next_cursor is None
    assert tuple(
        item.event_ref.event_id
        for item in repository.list_audit(as_of=as_of, cursor=None, limit=10).entries
    ) == ("event-1", "event-2", "event-3")

    with pytest.raises(ValueError, match="signature"):
        repository.list_audit(
            as_of=as_of,
            cursor=f"{first.next_cursor[:-1]}x",
            limit=1,
        )
    with override_settings(SECRET_KEY="another-signing-key"):
        with pytest.raises(ValueError, match="signature"):
            repository.list_audit(as_of=as_of, cursor=first.next_cursor, limit=1)


@pytest.mark.django_db(transaction=True)
def test_activation_restore_detects_raw_header_and_snapshot_tamper() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)
    clock.value = BASE + timedelta(days=1)
    page = repository.list_audit(
        as_of=BASE + timedelta(hours=1),
        cursor=None,
        limit=1,
    )
    assert page.next_cursor is not None

    with connection.cursor() as cursor:
        cursor.execute("UPDATE research_r6_activation_audit_snapshot SET entry_count = 99")
    with pytest.raises(R6ActivationCorruption, match="row header"):
        repository.list_audit(
            as_of=BASE + timedelta(hours=1),
            cursor=page.next_cursor,
            limit=1,
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r6_activation_event SET ledger_header_hash = %s "
            "WHERE event_id = %s",
            ["f" * 64, event_1.event_id],
        )
    with pytest.raises(R6ActivationCorruption, match="row header"):
        repository.get_exact_event(
            event_ref=R6ActivationEventRef(
                event_1.event_id,
                event_1.event_version,
                event_1.content_hash,
            ),
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_models_block_normal_django_mutation_shortcuts() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)
    clock.value = BASE + timedelta(days=1)
    repository.list_audit(as_of=BASE + timedelta(hours=1), cursor=None, limit=1)

    with pytest.raises(ValidationError, match="exact insert claim"):
        R6ActivationAuthorizationModel._default_manager.create()
    models = (
        R6ActivationAuthorizationModel._default_manager.get(
            authorization_id=authorization_1.authorization_id
        ),
        R6ActivationEventModel._default_manager.get(event_id=event_1.event_id),
        R6ActivationStreamCommitModel._default_manager.get(event_id=event_1.event_id),
        R6ActivationAuditSnapshotModel._default_manager.get(),
    )
    for model in models:
        with pytest.raises(ValidationError):
            model.save()
        with pytest.raises(ValidationError):
            model.save_base()
        with pytest.raises(ValidationError):
            model.delete()
        manager = type(model)._default_manager
        with pytest.raises(ValidationError):
            manager.bulk_create([model])
        with pytest.raises(ValidationError):
            manager.bulk_update([model], ["content_hash"])
        with pytest.raises(ValidationError):
            manager.get_or_create(pk=model.pk)
        with pytest.raises(ValidationError):
            manager.update_or_create(pk=model.pk)
        queryset = manager.all()
        with pytest.raises(ValidationError):
            queryset.update(content_hash="f" * 64)
        with pytest.raises(ValidationError):
            queryset.delete()
        with pytest.raises(ValidationError):
            queryset._update([])
        with pytest.raises(ValidationError):
            queryset._raw_delete("default")
        with pytest.raises(ValidationError):
            queryset._insert([], [])
        with pytest.raises(ValidationError):
            queryset._batched_insert([], [], None)
        with pytest.raises(ValidationError):
            type(model)._base_manager.update(content_hash="f" * 64)

    related_event = models[0].activation_event
    with pytest.raises(ValidationError):
        related_event.save()
    assert models[0].activation_stream_commit == models[2]
    assert models[1].activation_stream_commit == models[2]
    with transaction.atomic():
        collector = Collector(using="default")
        with pytest.raises(ProtectedError):
            collector.collect([models[1]])
    with transaction.atomic():
        collector = Collector(using="default")
        collector.collect([models[2]])
        with transaction.atomic():
            with pytest.raises(ValidationError, match="cannot be deleted"):
                collector.delete()


@pytest.mark.django_db(transaction=True)
def test_activation_restore_detects_raw_authorization_payload_tamper() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization, event = _transition(1, ())
    _append(store, authorization, event)
    model = R6ActivationAuthorizationModel._default_manager.get()
    payload = model.canonical_payload
    payload["authorization"]["evidence_ref"] = "research://tampered"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r6_activation_authorization SET canonical_payload = %s "
            "WHERE id = %s",
            [json.dumps(payload), model.pk],
        )
    with pytest.raises(R6ActivationCorruption, match="payload is invalid"):
        repository.get_exact_authorization(
            authorization_ref=authorization.ref,
            expected_hash=authorization.content_hash,
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_restore_detects_raw_foreign_key_alias() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)
    repository = store
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)
    authorization_row_2 = R6ActivationAuthorizationModel._default_manager.get(
        authorization_id=authorization_2.authorization_id
    )
    with connection.constraint_checks_disabled(), connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_r6_activation_event WHERE event_id = %s",
            [event_2.event_id],
        )
        cursor.execute(
            "UPDATE research_r6_activation_event SET authorization_row_id = %s "
            "WHERE event_id = %s",
            [authorization_row_2.pk, event_1.event_id],
        )
    with pytest.raises(R6ActivationCorruption, match="truncated or orphaned|row header differs"):
        repository.get_exact_event(
            event_ref=R6ActivationEventRef(
                event_1.event_id,
                event_1.event_version,
                event_1.content_hash,
            ),
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_ledger_clock_prevents_historical_backfill() -> None:
    ledger_time = BASE + timedelta(days=1)
    clock = FixedClock(ledger_time)
    store = _DjangoR6ActivationStore(clock=clock)
    authorization, event = _transition(1, ())
    _append(
        store,
        authorization,
        event,
        ledger_recorded_at=ledger_time,
    )

    historical_cutoff = event.recorded_at + timedelta(hours=1)
    assert (
        store.get_exact_event(
            event_ref=R6ActivationEventRef(
                event.event_id,
                event.event_version,
                event.content_hash,
            ),
            as_of=historical_cutoff,
        )
        is None
    )
    assert (
        store.get_exact_authorization(
            authorization_ref=authorization.ref,
            expected_hash=authorization.content_hash,
            as_of=historical_cutoff,
        )
        is None
    )
    event_row = R6ActivationEventModel._default_manager.get()
    authorization_row = R6ActivationAuthorizationModel._default_manager.get()
    assert event_row.ledger_recorded_at == ledger_time
    assert authorization_row.ledger_recorded_at == ledger_time


@pytest.mark.django_db(transaction=True)
def test_activation_stream_and_exact_authorization_reject_orphaned_tail() -> None:
    clock = FixedClock(BASE)
    store = _DjangoR6ActivationStore(clock=clock)
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)

    with connection.constraint_checks_disabled(), connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_r6_activation_event WHERE event_id = %s",
            [event_2.event_id],
        )

    with store.atomic():
        with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
            store.load_stream(scope_ref=authorization_1.scope_ref, as_of=clock.value)
    with pytest.raises(R6ActivationCorruption, match="orphaned"):
        store.get_exact_authorization(
            authorization_ref=authorization_2.ref,
            expected_hash=authorization_2.content_hash,
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_stream_and_exact_reads_reject_paired_tail_truncation() -> None:
    clock = FixedClock(BASE)
    store = _DjangoR6ActivationStore(clock=clock)
    authorization_1, event_1 = _transition(1, ())
    _append(store, authorization_1, event_1)
    authorization_2, event_2 = _transition(2, (event_1,))
    _append(store, authorization_2, event_2)

    with connection.constraint_checks_disabled(), connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_r6_activation_event WHERE event_id = %s",
            [event_2.event_id],
        )
        cursor.execute(
            "DELETE FROM research_r6_activation_authorization WHERE authorization_id = %s",
            [authorization_2.authorization_id],
        )

    with store.atomic():
        with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
            store.load_stream(scope_ref=authorization_1.scope_ref, as_of=clock.value)
    with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
        store.get_exact_authorization(
            authorization_ref=authorization_2.ref,
            expected_hash=authorization_2.content_hash,
            as_of=clock.value,
        )
    with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
        store.get_exact_event(
            event_ref=R6ActivationEventRef(
                event_2.event_id,
                event_2.event_version,
                event_2.content_hash,
            ),
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_stream_and_exact_reads_reject_missing_commit_anchor() -> None:
    clock = FixedClock(BASE)
    store = _DjangoR6ActivationStore(clock=clock)
    authorization, event = _transition(1, ())
    _append(store, authorization, event)

    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM research_r6_activation_stream_commit WHERE event_id = %s",
            [event.event_id],
        )

    with store.atomic():
        with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
            store.load_stream(scope_ref=authorization.scope_ref, as_of=clock.value)
    with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
        store.get_exact_authorization(
            authorization_ref=authorization.ref,
            expected_hash=authorization.content_hash,
            as_of=clock.value,
        )
    with pytest.raises(R6ActivationCorruption, match="truncated or orphaned"):
        store.get_exact_event(
            event_ref=R6ActivationEventRef(
                event.event_id,
                event.event_version,
                event.content_hash,
            ),
            as_of=clock.value,
        )


@pytest.mark.django_db(transaction=True)
def test_activation_stream_keeps_scope_versions_isolated() -> None:
    clock = FixedClock(BASE)
    store = _DjangoR6ActivationStore(clock=clock)
    authorization_v1, event_v1 = _transition(1, ())
    _append(store, authorization_v1, event_v1)

    scope_v2 = R6ActivationScopeRef("scope-1", "v2", "b" * 64)
    instant = BASE + timedelta(minutes=5)
    authorization_v2 = R6ActivationAuthorization(
        authorization_id="authorization-v2",
        authorization_version="v1",
        event_id="event-v2",
        event_version="v1",
        scope_ref=scope_v2,
        action=R6ActivationAction.ACTIVATE,
        subject=R6ActivationApprovalRef("approval-v2", "v1", "c" * 64),
        rollback_target=None,
        expected_sequence=1,
        expected_previous_event_hash=None,
        owner="research",
        issued_at=instant,
        recorded_at=instant + timedelta(seconds=1),
        valid_until=instant + timedelta(hours=1),
        reason_codes=("manual-approval",),
        evidence_ref="research://activation/authorization-v2",
    )
    event_v2 = create_r6_activation_event(
        authorization=authorization_v2,
        previous_events=(),
        applied_at=instant + timedelta(seconds=2),
    )
    _append(store, authorization_v2, event_v2)

    with store.atomic():
        assert store.load_stream(
            scope_ref=authorization_v1.scope_ref,
            as_of=clock.value,
        ) == (event_v1,)
        assert store.load_stream(scope_ref=scope_v2, as_of=clock.value) == (event_v2,)


@pytest.mark.django_db(transaction=True)
def test_activation_audit_limit_rejects_comparison_overriding_int_subclass() -> None:
    clock = FixedClock(BASE + timedelta(days=1))
    store = _DjangoR6ActivationStore(clock=clock)

    with pytest.raises(ValueError, match="between 1 and 200"):
        AuditR6ActivationEventsCommand(
            as_of=clock.value,
            limit=WideInt(10_000_000),
        )
    with pytest.raises(ValueError, match="between 1 and 200"):
        store.list_audit(
            as_of=clock.value,
            cursor=None,
            limit=WideInt(10_000_000),
        )
