"""Application contracts for the four-step calendar publication journey."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarFormalPublicationPort,
    CalendarPublicationOperationsError,
    CalendarPublicationPreparationContext,
    CalendarPublicationPreparationPort,
    CalendarPublicationPreview,
    CalendarSnapshotCapturePort,
    CaptureExchangeCalendarSnapshotIntent,
    CaptureExchangeCalendarSnapshotUseCase,
    ConfirmCalendarPublicationUseCase,
    PreviewCalendarPublicationIntent,
    PreviewCalendarPublicationUseCase,
    ReadCurrentCalendarIntent,
    ReadCurrentCalendarUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarCurrentPublicationReaderPort,
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
    CalendarPublicationAuditPair,
    CalendarPublicationTransition,
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    ExchangeCalendarSnapshotReference,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
    CalendarPublicationPointerExpectation,
    create_calendar_formal_publication_seal,
)
from core.exceptions import AuthorizationError, MissingConfigError

NOW = datetime(2026, 10, 16, 4, 0, 10, tzinfo=UTC)
CALENDAR_DAY = date(2026, 10, 16)
DATASET = DatasetKey("tushare.exchange_calendar.raw", "1.0", "1.0")


def _snapshot(*, first_seen_at: datetime | None = None) -> ExchangeCalendarSnapshot:
    """Build one exact retained-source snapshot for application tests."""

    seen = first_seen_at or NOW - timedelta(seconds=20)
    raw = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", CALENDAR_DAY, CALENDAR_DAY
        ),
        original_body_retained=True,
        response_completed_at=seen,
        provider_name="tushare",
        dataset_key=DATASET.value,
        transport="direct",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SSE",
        coverage_start=CALENDAR_DAY,
        coverage_end=CALENDAR_DAY,
        days=(
            ExchangeCalendarDay(
                exchange="SSE",
                calendar_date=CALENDAR_DAY,
                is_open=True,
                previous_open_date=date(2026, 10, 15),
            ),
        ),
        provider_name="tushare",
        raw_reference=raw,
        first_seen_at=seen,
        source_published_at=None,
    )
    return make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=seen + timedelta(seconds=1),
    )


def _context(
    snapshot: ExchangeCalendarSnapshot | None = None,
    *,
    ttl: int = 60,
    pointer: CalendarPublicationPointerExpectation | None = None,
) -> CalendarPublicationPreparationContext:
    """Build exact source, versioned catalog and pointer evidence."""

    selected = snapshot or _snapshot()
    policy = PublicationPolicy(
        dataset=DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fetched_at", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-policy-1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    contract = DatasetContract(
        key=DATASET,
        owner="data_center",
        frequency="daily",
        decision_critical=False,
        fields=(DatasetFieldContract("is_open", "boolean", None, False, False),),
        calendar_response_max_age_seconds=ttl,
    )
    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-placeholder",
        dataset_key=DATASET.value,
        natural_key=f"SSE:{selected.coverage_start.isoformat()}:{selected.coverage_end.isoformat()}",
        source=selected.provider_name,
        source_record_id=selected.snapshot_id,
        fact_table="data_center_exchange_calendar_snapshot_fact",
        fact_pk=selected.snapshot_id,
        observed_at=None,
        raw_payload_hash=selected.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=selected.first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    member_reference = CalendarPublicationMemberReference(
        member=member,
        snapshot_content_hash=selected.content_hash,
        snapshot_record_digest=selected.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    absent = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key="exchange-calendar:SSE",
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    return CalendarPublicationPreparationContext(
        snapshot=selected,
        contract=contract,
        contract_recorded_at=NOW - timedelta(days=2),
        policy=policy,
        policy_recorded_at=NOW - timedelta(days=1),
        member_reference=member_reference,
        current_pointer=pointer or absent,
    )


class FixedClock:
    """Return one deterministic server clock value."""

    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class FixedActivationIdFactory:
    """Return one explicit activation identity for preview creation."""

    def __init__(self, value: str = "calendar-activation-1") -> None:
        self.value = value

    def new_id(self) -> str:
        return self.value


class SequenceActivationIdFactory:
    """Return distinct IDs so preview reuse behavior is observable."""

    def __init__(self) -> None:
        self.calls = 0

    def new_id(self) -> str:
        self.calls += 1
        return f"calendar-activation-{self.calls}"


class SnapshotCapture:
    """Capture one source-bound snapshot without caller-controlled source data."""

    def __init__(self, snapshot: ExchangeCalendarSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, date, date]] = []

    def execute(
        self, exchange: str, coverage_start: date, coverage_end: date
    ) -> ExchangeCalendarSnapshot:
        self.calls.append((exchange, coverage_start, coverage_end))
        return self.snapshot


class PreparationReader:
    """Return a typed preparation context for one exact source reference."""

    def __init__(self, context: CalendarPublicationPreparationContext) -> None:
        self.context = context
        self.calls: list[tuple[ExchangeCalendarSnapshotReference, datetime]] = []

    def load_exact(
        self, reference: ExchangeCalendarSnapshotReference, *, known_at: datetime
    ) -> CalendarPublicationPreparationContext:
        self.calls.append((reference, known_at))
        if reference != self.context.snapshot.reference():
            raise CalendarPublicationOperationsError(
                "Exact source snapshot was not found",
                code="CALENDAR_PUBLICATION_SOURCE_NOT_FOUND",
            )
        return self.context


class Publisher:
    """Record one typed formal publication request and return its exact commit."""

    def __init__(self) -> None:
        self.requests: list[CalendarFormalPublicationRequest] = []
        self.commit: CalendarFormalPublicationCommit | None = None

    def execute(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        self.requests.append(request)
        if self.commit is not None:
            return replace(
                self.commit,
                transition=CalendarPublicationTransition.EXACT_CURRENT_REPLAY,
            )
        published_at = NOW
        record = CalendarFormalPublicationRecord(
            seal=request.proposed_seal,
            publication_id=str(uuid4()),
            activation_id=request.activation_id,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            published_at=published_at,
        )
        pointer = CalendarPublicationPointerExpectation(
            dataset_key=record.seal.dataset.value,
            publication_key=record.seal.publication_key,
            pointer_id=str(uuid4()),
            publication_id=record.publication_id,
            publication_hash=record.seal.publication_hash,
            activation_id=record.activation_id,
            updated_at=published_at,
        )
        event_id = "calendar-event-1"
        audit = CalendarPublicationAuditPair(
            database_alias="default",
            dataset_key=record.seal.dataset.value,
            exchange=record.seal.exchange,
            publication_id=record.publication_id,
            publication_hash=record.seal.publication_hash,
            event_id=event_id,
            event_content_hash="b" * 64,
            actor_user_id=11,
            outbox_id=uuid4(),
            idempotency_key=event_id,
            recorded_at=published_at,
        )
        self.commit = CalendarFormalPublicationCommit(
            record=record,
            pointer=pointer,
            transition=CalendarPublicationTransition.FIRST_PUBLISH,
            audit_pair=audit,
            post_audit_checked_at=published_at + timedelta(seconds=1),
        )
        return self.commit


class PublisherPrincipal:
    """Provide the exact active permission lease expected by the formal use case."""

    actor_type = "django_user"
    actor_id = "django-user:11"
    permission_codename = CALENDAR_PUBLISH_PERMISSION_CODENAME
    database_alias = "default"
    user_id = 11
    permission_id = 7
    verified_at = NOW - timedelta(seconds=1)

    def __init__(self) -> None:
        self.assert_live_calls = 0

    def assert_live(self) -> None:
        self.assert_live_calls += 1


def _make_preview(
    context: CalendarPublicationPreparationContext | None = None,
    *,
    now: datetime = NOW,
) -> tuple[CalendarPublicationPreview, PreparationReader, PublisherPrincipal]:
    selected = context or _context()
    reader = PreparationReader(selected)
    principal = PublisherPrincipal()
    use_case = PreviewCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        clock=FixedClock(now),
        activation_ids=FixedActivationIdFactory(),
    )
    preview = use_case.execute(
        PreviewCalendarPublicationIntent(snapshot_reference=selected.snapshot.reference()),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )
    return preview, reader, principal


def test_capture_takes_only_explicit_scope_and_returns_unpublished_reference() -> None:
    snapshot = _snapshot()
    source = SnapshotCapture(snapshot)
    use_case = CaptureExchangeCalendarSnapshotUseCase(source=source)

    result = use_case.execute(
        CaptureExchangeCalendarSnapshotIntent(
            exchange="SSE",
            coverage_start=CALENDAR_DAY,
            coverage_end=CALENDAR_DAY,
        )
    )

    assert source.calls == [("SSE", CALENDAR_DAY, CALENDAR_DAY)]
    assert result.snapshot_reference == snapshot.reference()
    assert result.first_seen_at == snapshot.first_seen_at
    assert result.recorded_at == snapshot.recorded_at
    assert result.source_published_at is None
    assert result.must_not_execute is True


def test_capture_rejects_a_source_result_for_another_scope() -> None:
    source = SnapshotCapture(_snapshot())
    use_case = CaptureExchangeCalendarSnapshotUseCase(source=source)

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            CaptureExchangeCalendarSnapshotIntent(
                exchange="SZSE",
                coverage_start=CALENDAR_DAY,
                coverage_end=CALENDAR_DAY,
            )
        )

    assert caught.value.code == "CALENDAR_CAPTURE_SCOPE_MISMATCH"


def test_capture_rejects_an_untyped_source_result() -> None:
    class InvalidSource:
        def execute(self, exchange: str, coverage_start: date, coverage_end: date) -> object:
            return object()

    use_case = CaptureExchangeCalendarSnapshotUseCase(
        source=cast(CalendarSnapshotCapturePort, InvalidSource())
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            CaptureExchangeCalendarSnapshotIntent(
                exchange="SSE",
                coverage_start=CALENDAR_DAY,
                coverage_end=CALENDAR_DAY,
            )
        )

    assert caught.value.code == "CALENDAR_CAPTURE_RESULT_INVALID"


def test_preview_builds_machine_echoable_context_without_exposing_seal() -> None:
    preview, reader, principal = _make_preview()

    assert preview.snapshot_reference == reader.context.snapshot.reference()
    assert preview.identity.dataset_key == DATASET.value
    assert preview.identity.contract_version == DATASET.contract_version
    assert preview.identity.schema_version == DATASET.schema_version
    assert preview.identity.policy_version == "calendar-policy-1"
    assert preview.identity.calendar_response_max_age_seconds == 60
    assert preview.response_expires_at == reader.context.snapshot.first_seen_at + timedelta(
        seconds=60
    )
    assert preview.expected_pointer.is_absent is True
    assert preview.activation_id == "calendar-activation-1"
    assert len(preview.expected_publication_hash) == 64
    assert len(preview.preview_hash) == 64
    assert not hasattr(preview, "seal")
    assert preview.must_not_execute is True
    assert reader.calls == [(preview.snapshot_reference, NOW)]
    assert principal.assert_live_calls >= 2


def test_preview_rejects_source_when_response_ttl_has_expired() -> None:
    snapshot = _snapshot(first_seen_at=NOW - timedelta(seconds=90))
    with pytest.raises(CalendarPublicationOperationsError) as caught:
        _make_preview(_context(snapshot, ttl=60), now=NOW)

    assert caught.value.code == "CALENDAR_PUBLICATION_RESPONSE_EXPIRED"


def test_preview_fails_closed_when_exact_preparation_is_unavailable() -> None:
    class MissingPreparation:
        def load_exact(
            self,
            reference: ExchangeCalendarSnapshotReference,
            *,
            known_at: datetime,
        ) -> CalendarPublicationPreparationContext | None:
            return None

    use_case = PreviewCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, MissingPreparation()),
        clock=FixedClock(NOW),
        activation_ids=FixedActivationIdFactory(),
    )

    with pytest.raises(MissingConfigError) as caught:
        use_case.execute(
            PreviewCalendarPublicationIntent(_snapshot().reference()),
            principal=cast(LockedCalendarPublisherPrincipal, PublisherPrincipal()),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_PREPARATION_UNAVAILABLE"


def test_preview_rejects_untrusted_or_wrong_scope_principal() -> None:
    preview_reader = PreparationReader(_context())
    principal = PublisherPrincipal()
    principal.permission_codename = "view_exchange_calendar_publication_audit"
    use_case = PreviewCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, preview_reader),
        clock=FixedClock(NOW),
        activation_ids=FixedActivationIdFactory(),
    )

    with pytest.raises(AuthorizationError) as caught:
        use_case.execute(
            PreviewCalendarPublicationIntent(_context().snapshot.reference()),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLISHER_AUTHORITY_INVALID"


def test_confirmation_rebuilds_seal_and_publishes_only_exact_preview() -> None:
    preview, reader, principal = _make_preview()
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    result = use_case.execute(
        preview.confirmation_intent(),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )

    assert len(publisher.requests) == 1
    request = publisher.requests[0]
    assert request.proposed_seal.publication_hash == preview.expected_publication_hash
    assert request.expected_pointer == preview.expected_pointer
    assert request.activation_id == preview.activation_id
    assert result.record.seal.publication_hash == preview.expected_publication_hash
    assert result.audit_pair.recorded_at == NOW
    assert principal.assert_live_calls >= 2


@pytest.mark.parametrize("mismatch", ("actor", "alias"))
def test_confirmation_rejects_receipt_not_bound_to_current_authority(
    mismatch: str,
) -> None:
    preview, reader, principal = _make_preview()
    if mismatch == "actor":
        principal.user_id = 12
        principal.actor_id = "django-user:12"
    else:
        principal.database_alias = "other"
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            preview.confirmation_intent(),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_COMMIT_BINDING_INVALID"


def test_confirmation_rejects_changed_catalog_before_writing() -> None:
    preview, reader, principal = _make_preview()
    changed = replace(
        reader.context,
        contract=replace(reader.context.contract, calendar_response_max_age_seconds=59),
    )
    reader.context = changed
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            preview.confirmation_intent(),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_PREVIEW_STALE"
    assert publisher.requests == []


def test_confirmation_fails_closed_when_exact_preparation_disappears() -> None:
    preview, _, principal = _make_preview()

    class MissingPreparation:
        def load_exact(
            self,
            reference: ExchangeCalendarSnapshotReference,
            *,
            known_at: datetime,
        ) -> CalendarPublicationPreparationContext | None:
            return None

    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, MissingPreparation()),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            preview.confirmation_intent(),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_PREVIEW_STALE"
    assert publisher.requests == []


def test_confirmation_rejects_modified_preview_hash_before_writing() -> None:
    preview, reader, principal = _make_preview()
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            replace(preview.confirmation_intent(), preview_hash="f" * 64),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_PREVIEW_HASH_MISMATCH"
    assert publisher.requests == []


def test_confirmation_rejects_changed_pointer_cas_before_writing() -> None:
    preview, reader, principal = _make_preview()
    reader.context = replace(
        reader.context,
        current_pointer=replace(
            reader.context.current_pointer,
            pointer_id=str(uuid4()),
            publication_id=str(uuid4()),
            publication_hash="c" * 64,
            activation_id="previous-activation",
            updated_at=NOW - timedelta(seconds=1),
        ),
    )
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(
            preview.confirmation_intent(),
            principal=cast(LockedCalendarPublisherPrincipal, principal),
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_POINTER_CHANGED"
    assert publisher.requests == []


def test_original_first_publish_confirmation_can_replay_exact_current_winner() -> None:
    preview, reader, principal = _make_preview()
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )
    original_intent = preview.confirmation_intent()
    first = use_case.execute(
        original_intent,
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )
    reader.context = replace(reader.context, current_pointer=first.pointer)

    replay = use_case.execute(
        original_intent,
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )

    assert len(publisher.requests) == 2
    assert publisher.requests[0].expected_pointer.is_absent
    assert publisher.requests[1].expected_pointer == first.pointer
    assert replay.transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY
    assert replay.record == first.record
    assert replay.audit_pair == first.audit_pair


def test_original_forward_publish_confirmation_can_replay_exact_current_winner() -> None:
    before = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key="exchange-calendar:SSE",
        pointer_id=str(uuid4()),
        publication_id=str(uuid4()),
        publication_hash="9" * 64,
        activation_id="previous-activation",
        updated_at=NOW - timedelta(seconds=5),
    )
    context = _context(pointer=before)
    preview, reader, principal = _make_preview(context)
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )
    original_intent = preview.confirmation_intent()
    first = use_case.execute(
        original_intent,
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )
    reader.context = replace(reader.context, current_pointer=first.pointer)

    replay = use_case.execute(
        original_intent,
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )

    assert len(publisher.requests) == 2
    assert publisher.requests[0].expected_pointer == before
    assert publisher.requests[1].expected_pointer == first.pointer
    assert replay.transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY


def test_new_preview_reuses_activation_when_exact_content_is_current() -> None:
    initial = _context()
    preview, reader, principal = _make_preview(initial)
    publisher = Publisher()
    confirmation = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )
    commit = confirmation.execute(
        preview.confirmation_intent(),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )
    reader.context = replace(reader.context, current_pointer=commit.pointer)
    activation_ids = SequenceActivationIdFactory()
    preview_usecase = PreviewCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        clock=FixedClock(NOW),
        activation_ids=activation_ids,
    )

    repeated_preview = preview_usecase.execute(
        PreviewCalendarPublicationIntent(initial.snapshot.reference()),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )

    assert repeated_preview.expected_pointer == commit.pointer
    assert repeated_preview.activation_id == commit.record.activation_id
    assert activation_ids.calls == 0


def test_current_read_uses_server_clock_and_preserves_non_execution_boundary() -> None:
    snapshot = _snapshot()
    seal = create_calendar_formal_publication_seal(
        dataset=DATASET,
        exchange="SSE",
        calendar_response_max_age_seconds=60,
        contract_recorded_at=NOW - timedelta(days=2),
        policy=_context(snapshot).policy,
        policy_recorded_at=NOW - timedelta(days=1),
        snapshot=snapshot,
        member_reference=_context(snapshot).member_reference,
    )
    record = CalendarFormalPublicationRecord(
        seal=seal,
        publication_id=str(uuid4()),
        activation_id="calendar-activation-1",
        lifecycle=CalendarPublicationLifecycle.PUBLISHED,
        published_at=NOW - timedelta(seconds=5),
    )
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=seal.publication_hash,
        activation_id=record.activation_id,
        updated_at=record.published_at,
    )

    class CurrentReader:
        query = None

        def read_current(self, query: object) -> CurrentPublishedExchangeCalendar:
            self.query = query
            return CurrentPublishedExchangeCalendar(record=record, pointer=pointer, as_of=NOW)

    reader = CurrentReader()
    clock = FixedClock(NOW)
    use_case = ReadCurrentCalendarUseCase(
        reader=cast(CalendarCurrentPublicationReaderPort, reader), clock=clock
    )

    result = use_case.execute(ReadCurrentCalendarIntent(dataset_key=DATASET.value, exchange="SSE"))

    assert result.as_of == NOW
    assert result.must_not_execute is True
    assert reader.query.as_of == NOW
    assert clock.calls == 1


def test_current_read_returns_none_when_no_exact_pointer_exists() -> None:
    class MissingReader:
        def read_current(self, query: object) -> None:
            return None

    clock = FixedClock(NOW)
    use_case = ReadCurrentCalendarUseCase(
        reader=cast(CalendarCurrentPublicationReaderPort, MissingReader()),
        clock=clock,
    )

    result = use_case.execute(ReadCurrentCalendarIntent(dataset_key=DATASET.value, exchange="SSE"))

    assert result is None
    assert clock.calls == 1


def test_current_read_rejects_an_untyped_repository_result() -> None:
    class InvalidReader:
        def read_current(self, query: object) -> object:
            return object()

    use_case = ReadCurrentCalendarUseCase(
        reader=cast(CalendarCurrentPublicationReaderPort, InvalidReader()),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(ReadCurrentCalendarIntent(dataset_key=DATASET.value, exchange="SSE"))

    assert caught.value.code == "CALENDAR_CURRENT_READ_RESULT_INVALID"


@pytest.mark.parametrize(
    ("dataset_key", "exchange"),
    (("tushare.other_calendar.raw", "SSE"), (DATASET.value, "SZSE")),
)
def test_current_read_rejects_a_valid_result_for_another_scope(
    dataset_key: str,
    exchange: str,
) -> None:
    snapshot = _snapshot()
    seal = create_calendar_formal_publication_seal(
        dataset=DATASET,
        exchange="SSE",
        calendar_response_max_age_seconds=60,
        contract_recorded_at=NOW - timedelta(days=2),
        policy=_context(snapshot).policy,
        policy_recorded_at=NOW - timedelta(days=1),
        snapshot=snapshot,
        member_reference=_context(snapshot).member_reference,
    )
    record = CalendarFormalPublicationRecord(
        seal=seal,
        publication_id=str(uuid4()),
        activation_id="calendar-activation-1",
        lifecycle=CalendarPublicationLifecycle.PUBLISHED,
        published_at=NOW - timedelta(seconds=5),
    )
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=seal.publication_hash,
        activation_id=record.activation_id,
        updated_at=record.published_at,
    )

    class CurrentReader:
        def read_current(self, query: object) -> CurrentPublishedExchangeCalendar:
            return CurrentPublishedExchangeCalendar(record=record, pointer=pointer, as_of=NOW)

    use_case = ReadCurrentCalendarUseCase(
        reader=cast(CalendarCurrentPublicationReaderPort, CurrentReader()),
        clock=FixedClock(NOW),
    )

    with pytest.raises(CalendarPublicationOperationsError) as caught:
        use_case.execute(ReadCurrentCalendarIntent(dataset_key=dataset_key, exchange=exchange))

    assert caught.value.code == "CALENDAR_CURRENT_READ_SCOPE_MISMATCH"
