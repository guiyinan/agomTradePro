from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from apps.audit.application.price_limit_publication_audit import (
    PriceLimitPublicationAuditConflict,
    PriceLimitPublicationAuditCorruption,
    PriceLimitPublicationAuditUseCase,
    build_price_limit_publication_event,
)
from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationTimelineEvent,
)
from core.integration.price_limit_formal_publication_audit import (
    build_price_limit_publication_audit_detail,
)
from tests.unit.audit.test_price_limit_publication_audit import (
    _NOW,
    _first_transition,
    _Principal,
    _record,
    _rollback_transition,
)


class _MemoryPriceLimitAuditWriter:
    """In-memory exact event/outbox port for application replay contracts."""

    def __init__(self) -> None:
        self.database_alias = "default"
        self.events: dict[str, SystemAuditEvent] = {}
        self.outboxes: dict[str, ExactSystemAuditOutboxWinner] = {}
        self.orphan_outboxes: dict[str, ExactSystemAuditOutboxWinner] = {}
        self.head: SystemAuditEvent | None = None
        self.locked_streams: list[str] = []
        self.append_calls = 0

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        yield

    def lock_stream(self, stream_id: str) -> None:
        self.locked_streams.append(stream_id)

    def get_price_limit_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        publication_key: str | None,
        as_of: object,
    ) -> SystemAuditEvent | None:
        del as_of
        event = self.events.get(event_id)
        if (
            event is None
            or event.event_version != event_version
            or event.dataset_key != dataset_key
        ):
            return None
        if publication_key is not None:
            transition = event.detail.get("transition")
            if (
                not isinstance(transition, dict)
                or transition.get("publication_key") != publication_key
            ):
                return None
        return event

    def get_price_limit_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        as_of: object,
    ) -> SystemAuditEvent | None:
        del dataset_key, publication_key, as_of
        return self.head

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        return self.orphan_outboxes.get(event.event_id) or self.outboxes.get(event.event_id)

    def append_and_enqueue_price_limit_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: object,
        principal: object,
    ) -> SystemAuditEventOutboxCommit:
        del principal
        actual_predecessor = self.head.content_hash if self.head is not None else None
        assert actual_predecessor == expected_predecessor_hash
        assert event.recorded_at == recorded_at
        outbox = ExactSystemAuditOutboxWinner(
            outbox_id=uuid4(),
            event=event,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            payload_hash=event.content_hash,
        )
        self.events[event.event_id] = event
        self.outboxes[event.event_id] = outbox
        self.head = event
        self.append_calls += 1
        return SystemAuditEventOutboxCommit(
            event=event,
            outbox_id=outbox.outbox_id,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
        )


def _first_detail(record: PriceLimitFormalPublicationRecord):
    return build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=record.first_published_at,
    )


def _forward_detail(
    previous: PriceLimitFormalPublicationRecord,
    target: PriceLimitFormalPublicationRecord,
):
    transition = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id=target.first_activation_id,
        dataset_key=target.seal.dataset_contract.key.value,
        publication_key=target.seal.publication_key,
        previous_publication_id=previous.publication_id,
        previous_publication_hash=previous.publication_hash,
        target_publication_id=target.publication_id,
        target_publication_hash=target.publication_hash,
        transitioned_at=target.first_published_at,
    )
    return build_price_limit_publication_audit_detail(
        target,
        transition,
        observed_server_at=target.first_published_at,
    )


def test_append_writes_one_exact_first_publish_event_and_outbox_pair() -> None:
    record = _record(first_activation_id=str(uuid4()))
    writer = _MemoryPriceLimitAuditWriter()

    result = PriceLimitPublicationAuditUseCase(writer).append_transition_in_caller_transaction(
        _first_detail(record),
        principal=_Principal(),
        server_now=_NOW,
    )

    assert result.commit.event.scope is None
    assert result.commit.event.outcome.value == "published"
    assert result.commit.event.sequence_no == 1
    assert result.commit.event.predecessor_hash is None
    assert result.commit.outbox_id == writer.outboxes[result.commit.event_id].outbox_id
    assert writer.append_calls == 1
    assert len(writer.locked_streams) == 1


def test_verify_does_not_repair_missing_event_or_missing_outbox_half_pairs() -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    record = _record(first_activation_id=str(uuid4()))
    detail = _first_detail(record)
    principal = _Principal()
    writer = _MemoryPriceLimitAuditWriter()
    use_case = PriceLimitPublicationAuditUseCase(writer)

    with pytest.raises(PriceLimitPublicationAuditCorruption, match="no event winner"):
        use_case.verify_transition_in_caller_transaction(
            detail,
            principal=principal,
            server_now=_NOW,
        )
    assert not writer.events
    assert not writer.outboxes

    event = build_price_limit_publication_event(
        detail,
        principal=principal,
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    writer.events[event.event_id] = event
    writer.head = event
    with pytest.raises(PriceLimitPublicationAuditCorruption, match="no exact outbox winner"):
        use_case.verify_transition_in_caller_transaction(
            detail,
            principal=principal,
            server_now=_NOW,
        )
    assert not writer.outboxes
    assert writer.append_calls == 0


def test_exact_replay_verifies_the_stored_pair_without_appending_again() -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = _first_detail(record)
    writer = _MemoryPriceLimitAuditWriter()
    use_case = PriceLimitPublicationAuditUseCase(writer)
    appended = use_case.append_transition_in_caller_transaction(
        detail,
        principal=_Principal(),
        server_now=_NOW,
    )

    replayed = use_case.verify_transition_in_caller_transaction(
        detail,
        principal=_Principal(),
        server_now=_NOW,
    )

    assert replayed.commit == appended.commit
    assert writer.append_calls == 1
    assert len(writer.events) == len(writer.outboxes) == 1


def test_exact_replay_rejects_outbox_with_same_event_id_but_different_content_hash() -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = _first_detail(record)
    other_clock_detail = replace(
        detail,
        observed_server_at=_NOW + timedelta(seconds=1),
    )
    expected_event = build_price_limit_publication_event(
        detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    other_event = build_price_limit_publication_event(
        other_clock_detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    assert expected_event.event_id == other_event.event_id
    assert expected_event.content_hash != other_event.content_hash
    writer = _MemoryPriceLimitAuditWriter()
    writer.events[expected_event.event_id] = expected_event
    writer.head = expected_event
    writer.outboxes[expected_event.event_id] = ExactSystemAuditOutboxWinner(
        outbox_id=uuid4(),
        event=other_event,
        event_id=other_event.event_id,
        idempotency_key=other_event.idempotency_key,
        payload_hash=other_event.content_hash,
    )

    with pytest.raises(PriceLimitPublicationAuditCorruption, match="does not pair"):
        PriceLimitPublicationAuditUseCase(writer).verify_transition_in_caller_transaction(
            detail,
            principal=_Principal(),
            server_now=_NOW,
        )

    assert writer.append_calls == 0


def test_append_refuses_an_orphan_outbox_without_synthesizing_its_event() -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = _first_detail(record)
    event = build_price_limit_publication_event(
        detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    writer = _MemoryPriceLimitAuditWriter()
    writer.orphan_outboxes[event.event_id] = ExactSystemAuditOutboxWinner(
        outbox_id=uuid4(),
        event=event,
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        payload_hash=event.content_hash,
    )

    with pytest.raises(PriceLimitPublicationAuditCorruption, match="without its event winner"):
        PriceLimitPublicationAuditUseCase(writer).append_transition_in_caller_transaction(
            detail,
            principal=_Principal(),
            server_now=_NOW,
        )

    assert not writer.events
    assert writer.append_calls == 0
    assert event.event_id in writer.orphan_outboxes


def test_forward_append_binds_the_exact_previous_hash_and_monotonic_clock() -> None:
    previous = _record(first_activation_id=str(uuid4()))
    target = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    writer = _MemoryPriceLimitAuditWriter()
    use_case = PriceLimitPublicationAuditUseCase(writer)
    first = use_case.append_transition_in_caller_transaction(
        _first_detail(previous),
        principal=_Principal(),
        server_now=_NOW,
    )

    forward = use_case.append_transition_in_caller_transaction(
        _forward_detail(previous, target),
        principal=_Principal(),
        server_now=_NOW + timedelta(minutes=1),
    )

    assert first.commit.event.event_id != forward.commit.event.event_id
    assert forward.commit.event.sequence_no == 2
    assert forward.commit.event.predecessor_hash == first.commit.event.content_hash
    assert writer.head == forward.commit.event


def test_forward_append_rejects_a_different_audit_predecessor() -> None:
    previous = _record(first_activation_id=str(uuid4()))
    wrong_previous = _record(first_activation_id=str(uuid4()))
    target = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    writer = _MemoryPriceLimitAuditWriter()
    wrong_detail = _first_detail(wrong_previous)
    wrong_event = build_price_limit_publication_event(
        wrong_detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    writer.events[wrong_event.event_id] = wrong_event
    writer.outboxes[wrong_event.event_id] = ExactSystemAuditOutboxWinner(
        outbox_id=uuid4(),
        event=wrong_event,
        event_id=wrong_event.event_id,
        idempotency_key=wrong_event.idempotency_key,
        payload_hash=wrong_event.content_hash,
    )
    writer.head = wrong_event

    with pytest.raises(PriceLimitPublicationAuditConflict, match="predecessor differs"):
        PriceLimitPublicationAuditUseCase(writer).append_transition_in_caller_transaction(
            _forward_detail(previous, target),
            principal=_Principal(),
            server_now=_NOW + timedelta(minutes=1),
        )

    assert writer.head == wrong_event
    assert writer.append_calls == 0


def test_forward_append_rejects_a_head_without_its_exact_outbox_pair() -> None:
    previous = _record(first_activation_id=str(uuid4()))
    target = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    writer = _MemoryPriceLimitAuditWriter()
    head = build_price_limit_publication_event(
        _first_detail(previous),
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    writer.events[head.event_id] = head
    writer.head = head

    with pytest.raises(PriceLimitPublicationAuditCorruption, match="no exact outbox winner"):
        PriceLimitPublicationAuditUseCase(writer).append_transition_in_caller_transaction(
            _forward_detail(previous, target),
            principal=_Principal(),
            server_now=_NOW + timedelta(minutes=1),
        )

    assert writer.head == head
    assert writer.append_calls == 0


def test_rollback_requires_the_exact_previous_publication_event_and_outbox() -> None:
    previous = _record(first_activation_id=str(uuid4()))
    current = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    writer = _MemoryPriceLimitAuditWriter()
    use_case = PriceLimitPublicationAuditUseCase(writer)
    first = use_case.append_transition_in_caller_transaction(
        _first_detail(previous),
        principal=_Principal(),
        server_now=_NOW,
    )
    current_result = use_case.append_transition_in_caller_transaction(
        _forward_detail(previous, current),
        principal=_Principal(),
        server_now=_NOW + timedelta(minutes=1),
    )
    writer.events.pop(first.commit.event_id)
    writer.outboxes.pop(first.commit.event_id)
    assert writer.head == current_result.commit.event

    rollback = build_price_limit_publication_audit_detail(
        previous,
        _rollback_transition(previous=current, target=previous),
        observed_server_at=_NOW + timedelta(minutes=2),
    )
    with pytest.raises(PriceLimitPublicationAuditConflict, match="no previously published event"):
        use_case.append_transition_in_caller_transaction(
            rollback,
            principal=_Principal(),
            server_now=_NOW + timedelta(minutes=2),
        )

    assert writer.append_calls == 2
    assert writer.head is not None and writer.head.event_id != rollback.transition.event_id
