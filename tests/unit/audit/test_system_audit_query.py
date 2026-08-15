from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.audit.application.system_audit_query import (
    GetSystemAuditEventCommand,
    GetSystemAuditEventUseCase,
    ListSystemAuditEventsCommand,
    ListSystemAuditEventsUseCase,
    SystemAuditQueryCorruption,
    SystemAuditQueryUnavailable,
    SystemAuditReaderContext,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from tests.unit.audit.test_system_audit_event import make_event

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)


class FakeRepository:
    def __init__(self, events: tuple[SystemAuditEvent, ...]) -> None:
        self.events = events

    def list_events(self, *, stream_id: str, as_of: datetime) -> tuple[SystemAuditEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.stream_id == stream_id and event.recorded_at <= as_of
        )

    def get_exact_by_hash(
        self,
        *,
        event_id: str,
        event_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id
                and event.event_version == event_version
                and event.content_hash == expected_content_hash
                and event.recorded_at <= as_of
            ),
            None,
        )


def _reader(*, staff: bool = True) -> SystemAuditReaderContext:
    return SystemAuditReaderContext(
        actor_id="django-user:7",
        user_id=7,
        is_authenticated=True,
        is_staff=staff,
        role="admin",
    )


def test_staff_stream_query_is_paged_and_pit_bounded() -> None:
    first = make_event()
    # Rebuild the second event through the canonical constructor so its hashes
    # remain valid while keeping the test focused on query authorization.
    second = SystemAuditEvent.create(
        event_id=first.event_id,
        event_version="2",
        schema_version=first.schema_version,
        category=first.category,
        event_type=first.event_type,
        owner=first.owner,
        write_policy=first.write_policy,
        outcome=first.outcome,
        severity=first.severity,
        reason_codes=first.reason_codes,
        occurred_at=first.occurred_at,
        recorded_at=NOW,
        observed_at=first.observed_at,
        actor=first.actor,
        source_app=first.source_app,
        source_component=first.source_component,
        source_surface=first.source_surface,
        correlations=first.correlations,
        resource=first.resource,
        dataset_key=first.dataset_key,
        provider_key=first.provider_key,
        capability=first.capability,
        publication_id=first.publication_id,
        evidence_refs=first.evidence_refs,
        detail_schema=first.detail_schema,
        detail={"rows": 3, "source_status": "valid", "nested": {"ok": True}},
        stream_id=first.stream_id,
        sequence_no=2,
        predecessor_hash=first.content_hash,
        idempotency_key="fetch:run-1:second",
    )
    result = ListSystemAuditEventsUseCase(FakeRepository((first, second))).execute(
        ListSystemAuditEventsCommand(
            stream_id=first.stream_id,
            as_of=NOW,
            reader=_reader(),
            page_size=1,
        )
    )
    assert result.events == (first,)
    assert result.next_after_sequence_no == 1


def test_non_staff_reader_is_denied_before_repository_call() -> None:
    class ExplodingRepository(FakeRepository):
        def list_events(self, **kwargs: object) -> tuple[SystemAuditEvent, ...]:
            raise AssertionError("repository must not be called")

    with pytest.raises(SystemAuditQueryUnavailable, match="staff"):
        ListSystemAuditEventsUseCase(ExplodingRepository(())).execute(
            ListSystemAuditEventsCommand(
                stream_id="dataset:macro.pmi",
                as_of=NOW,
                reader=_reader(staff=False),
            )
        )


def test_staff_reader_with_unbound_actor_is_denied_before_repository_call() -> None:
    class ExplodingRepository(FakeRepository):
        def list_events(self, **kwargs: object) -> tuple[SystemAuditEvent, ...]:
            raise AssertionError("repository must not be called")

    with pytest.raises(SystemAuditQueryUnavailable, match="staff"):
        ListSystemAuditEventsUseCase(ExplodingRepository(())).execute(
            ListSystemAuditEventsCommand(
                stream_id="dataset:macro.pmi",
                as_of=NOW,
                reader=replace(_reader(), actor_id="service:collector"),
            )
        )


def test_exact_reader_rechecks_identity_version_and_hash() -> None:
    event = make_event()
    use_case = GetSystemAuditEventUseCase(FakeRepository((event,)))
    command = GetSystemAuditEventCommand(
        event_id=event.event_id,
        event_version=event.event_version,
        expected_content_hash=event.content_hash,
        as_of=NOW,
        reader=_reader(),
    )
    assert use_case.execute(command) == event
    assert use_case.execute(replace(command, expected_content_hash="b" * 64)) is None


def test_query_commands_reject_naive_clocks_and_invalid_reader_identity() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ListSystemAuditEventsCommand(
            stream_id="dataset:macro.pmi",
            as_of=datetime(2026, 8, 14, 12, 0),
            reader=_reader(),
        )
    with pytest.raises(ValueError, match="positive integer"):
        SystemAuditReaderContext(
            actor_id="django-user:7",
            user_id=True,
            is_authenticated=True,
            is_staff=True,
            role="admin",
        )


@pytest.mark.parametrize("field", ["actor_id", "role"])
@pytest.mark.parametrize("value", ["bad value", "x" * 193])
def test_reader_context_rejects_noncanonical_identity_tokens(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="bounded canonical token"):
        SystemAuditReaderContext(
            actor_id=value if field == "actor_id" else "django-user:7",
            user_id=7,
            is_authenticated=True,
            is_staff=True,
            role=value if field == "role" else "admin",
        )


def test_unsorted_repository_result_fails_closed() -> None:
    first = make_event()
    repository = FakeRepository((first, first))
    with pytest.raises(SystemAuditQueryCorruption, match="unsorted"):
        ListSystemAuditEventsUseCase(repository).execute(
            ListSystemAuditEventsCommand(
                stream_id=first.stream_id,
                as_of=NOW,
                reader=_reader(),
            )
        )
