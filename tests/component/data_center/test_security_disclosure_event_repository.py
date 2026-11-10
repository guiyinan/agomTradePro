"""SQLite contract for source-bound, append-only official disclosure facts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    AppendSecurityDisclosureListingCoverageUseCase,
    QuerySecurityDisclosureEventsUseCase,
    QuerySecurityDisclosureListingCoverageUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingCoverageStatus,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.security_disclosure_event_models import (
    SecurityDisclosureEventModel,
    SecurityDisclosureListingCoverageModel,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
    DjangoSecurityDisclosureListingCoverageRepository,
)
from core.exceptions import DataValidationError

pytestmark = pytest.mark.django_db

BODY_V1 = b"%PDF-1.7\nsource disclosure version one"
BODY_V2 = b"%PDF-1.7\nsource disclosure corrected version"
FIRST_SEEN_V1 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
FIRST_SEEN_V2 = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
REPOSITORY_NOW = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
LISTED_DOCUMENT_ID = "ab89c4f0-e32e-4f9a-a8bf-ff7c1a500001"
SECOND_LISTED_DOCUMENT_ID = "ab89c4f0-e32e-4f9a-a8bf-ff7c1a500002"


class _Clock:
    """Deterministic aware clock for isolated SQLite component tests."""

    def __init__(self, now: datetime = REPOSITORY_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _event(
    *,
    body: bytes = BODY_V1,
    revision: str = "rev-1",
    first_seen_at: datetime = FIRST_SEEN_V1,
    announced_at: date | datetime | None = date(2026, 9, 30),
    source_available_at: date | datetime | None = None,
    effective_at: date | datetime | None = date(2028, 1, 5),
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.CASH_DIVIDEND,
    source_event_id: str = "disclose-301237-001",
    source_url: str | None = None,
    supersedes_source_event_id: str | None = None,
    supersedes_source_revision_id: str | None = None,
) -> SecurityDisclosureEvent:
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="301237.SZ",
        source_security_code="301237",
        source_event_id=source_event_id,
        source_revision_id=revision,
        raw_event_type="利润分配预案",
        event_type=event_type,
        source_url=source_url
        or (
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-30/" f"{source_event_id}.PDF"
        ),
        source_document_body=body,
        first_seen_at=first_seen_at,
        announced_at=announced_at,
        source_available_at=source_available_at,
        effective_at=effective_at,
        supersedes_source_event_id=supersedes_source_event_id,
        supersedes_source_revision_id=supersedes_source_revision_id,
    )


def _repository(*, now: datetime = REPOSITORY_NOW) -> DjangoSecurityDisclosureEventRepository:
    return DjangoSecurityDisclosureEventRepository(clock=_Clock(now))


def _listing_entry(
    document_id: str,
    *,
    listing_id: str,
    announcement_id: int = 1225572157,
    title: str = "一心堂：2026年中期权益分派实施公告",
) -> SecurityDisclosureListingEntry:
    """Build one exact official source row for a bounded historical window."""

    return SecurityDisclosureListingEntry(
        listing_id=listing_id,
        announcement_id=announcement_id,
        title=title,
        published_on=date(2026, 9, 30),
        raw_publish_time="2026-09-30 00:00:00",
        source_document_id=document_id,
        source_url=(
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-30/" f"{document_id}.PDF"
        ),
    )


def _listing_proof(
    *,
    entries: tuple[SecurityDisclosureListingEntry, ...] | None = None,
    first_observed_at: datetime = FIRST_SEEN_V1,
    verified_at: datetime = FIRST_SEEN_V1 + timedelta(seconds=10),
) -> SecurityDisclosureListingCoverageProof:
    """Build one fully retained official listing window proof."""

    selected_entries = (
        entries
        if entries is not None
        else (
            _listing_entry(
                LISTED_DOCUMENT_ID,
                listing_id="c4c48ea5-7ebd-4e0d-a40b-ffe0d5df0001",
            ),
        )
    )
    return SecurityDisclosureListingCoverageProof(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="301237.SZ",
        start_on=date(2026, 9, 1),
        end_on=date(2026, 9, 30),
        first_observed_at=first_observed_at,
        verified_at=verified_at,
        announcement_count=len(selected_entries),
        entries=selected_entries,
        first_pass_page_body_sha256=("a" * 64,),
        second_pass_page_body_sha256=("b" * 64,),
    )


def _listing_query(
    *, now: datetime = REPOSITORY_NOW
) -> QuerySecurityDisclosureListingCoverageUseCase:
    """Compose the exact historical coverage query over test-owned repositories."""

    return QuerySecurityDisclosureListingCoverageUseCase(
        coverage_repository=DjangoSecurityDisclosureListingCoverageRepository(clock=_Clock(now)),
        event_repository=_repository(now=now),
    )


def _listing_scope(
    *,
    as_of: datetime = REPOSITORY_NOW,
    start_on: date = date(2026, 9, 1),
    end_on: date = date(2026, 9, 30),
) -> SecurityDisclosureListingCoverageReadScope:
    """Build the exact source window and independent knowledge cutoff request."""

    return SecurityDisclosureListingCoverageReadScope(
        asset_code="301237.SZ",
        start_on=start_on,
        end_on=end_on,
        as_of=as_of,
    )


def _append_listing_proof(
    proof: SecurityDisclosureListingCoverageProof,
) -> SecurityDisclosureListingCoverageAppendResult:
    """Persist one completed two-pass proof through the Application boundary."""

    return AppendSecurityDisclosureListingCoverageUseCase(
        DjangoSecurityDisclosureListingCoverageRepository(clock=_Clock())
    ).execute(proof)


def test_append_stores_source_evidence_and_original_clock_precision() -> None:
    event = _event(source_available_at=date(2026, 9, 30))
    result = AppendSecurityDisclosureEventUseCase(_repository()).execute(event, BODY_V1)

    row = SecurityDisclosureEventModel.objects.get()
    assert result.disposition is SecurityDisclosureEventAppendDisposition.STORED
    assert result.record.event == event
    assert row.source == "szse_official"
    assert row.source_event_id == "disclose-301237-001"
    assert row.source_revision_id == "rev-1"
    assert row.source_body_sha256 == event.source_body_sha256
    assert row.announced_at is None
    assert row.announced_on == date(2026, 9, 30)
    assert row.source_available_at is None
    assert row.source_available_on == date(2026, 9, 30)
    assert row.available_at == row.first_seen_at
    assert row.first_seen_at == FIRST_SEEN_V1
    assert row.available_at == FIRST_SEEN_V1
    assert row.available_at != row.source_available_on
    assert row.effective_on == date(2028, 1, 5)
    assert row.recorded_at == REPOSITORY_NOW


def test_duplicate_key_and_content_returns_first_capture_without_rewriting() -> None:
    repository = _repository()
    use_case = AppendSecurityDisclosureEventUseCase(repository)
    original = _event()
    replay = _event(first_seen_at=datetime(2026, 11, 9, 23, 0, tzinfo=UTC))

    first = use_case.execute(original, BODY_V1)
    second = use_case.execute(replay, BODY_V1)

    assert first.disposition is SecurityDisclosureEventAppendDisposition.STORED
    assert second.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
    assert second.record == first.record
    assert SecurityDisclosureEventModel.objects.count() == 1


def test_same_native_revision_with_different_document_conflicts() -> None:
    use_case = AppendSecurityDisclosureEventUseCase(_repository())
    use_case.execute(_event(), BODY_V1)
    conflicting = _event(body=BODY_V2)

    with pytest.raises(DataValidationError) as error:
        use_case.execute(conflicting, BODY_V2)

    assert error.value.code == "SECURITY_DISCLOSURE_EVENT_IDENTITY_CONFLICT"
    assert SecurityDisclosureEventModel.objects.count() == 1


def test_pit_cutoff_requires_durable_recording_and_includes_future_effective_event() -> None:
    repository = _repository()
    event = _event(effective_at=date(2028, 1, 5))
    AppendSecurityDisclosureEventUseCase(repository).execute(event, BODY_V1)
    query = QuerySecurityDisclosureEventsUseCase(repository)

    before_observation = query.execute(
        SecurityDisclosureEventReadScope(
            as_of=datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
            asset_code="301237.SZ",
        )
    )
    after_observation_before_recording = query.execute(
        SecurityDisclosureEventReadScope(
            as_of=FIRST_SEEN_V1,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="301237.SZ",
        )
    )
    after_recording = query.execute(
        SecurityDisclosureEventReadScope(
            as_of=REPOSITORY_NOW,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="301237.SZ",
        )
    )

    assert before_observation == ()
    assert after_observation_before_recording == ()
    assert len(after_recording) == 1
    assert after_recording[0].event.effective_at == date(2028, 1, 5)


def test_correction_is_available_only_after_source_and_recorded_cutoffs() -> None:
    original_repository = _repository(now=FIRST_SEEN_V1 + timedelta(hours=1))
    correction_repository = _repository()
    original = _event()
    correction = _event(
        body=BODY_V2,
        revision="rev-2",
        first_seen_at=FIRST_SEEN_V2,
        announced_at=date(2026, 11, 4),
        supersedes_source_event_id="disclose-301237-001",
        supersedes_source_revision_id="rev-1",
    )
    AppendSecurityDisclosureEventUseCase(original_repository).execute(original, BODY_V1)
    AppendSecurityDisclosureEventUseCase(correction_repository).execute(correction, BODY_V2)
    query = QuerySecurityDisclosureEventsUseCase(correction_repository)

    earlier = query.execute(
        SecurityDisclosureEventReadScope(as_of=datetime(2026, 11, 4, 23, tzinfo=UTC))
    )
    after_source_before_recording = query.execute(
        SecurityDisclosureEventReadScope(as_of=FIRST_SEEN_V2)
    )
    later = query.execute(SecurityDisclosureEventReadScope(as_of=REPOSITORY_NOW))

    assert [record.event.source_revision_id for record in earlier] == ["rev-1"]
    assert [record.event.source_revision_id for record in after_source_before_recording] == [
        "rev-1"
    ]
    assert [record.event.source_revision_id for record in later] == ["rev-1", "rev-2"]
    assert later[1].event.supersedes_source_revision_id == "rev-1"


def test_future_first_seen_and_future_cutoff_fail_closed() -> None:
    event = _event(first_seen_at=datetime(2026, 11, 11, tzinfo=UTC))

    with pytest.raises(DataValidationError) as append_error:
        AppendSecurityDisclosureEventUseCase(_repository()).execute(event, BODY_V1)
    with pytest.raises(DataValidationError) as query_error:
        QuerySecurityDisclosureEventsUseCase(_repository()).execute(
            SecurityDisclosureEventReadScope(as_of=datetime(2026, 11, 11, tzinfo=UTC))
        )

    assert append_error.value.code == "SECURITY_DISCLOSURE_EVENT_CLOCK_INVALID"
    assert query_error.value.code == "SECURITY_DISCLOSURE_EVENT_CUTOFF_INVALID"
    assert SecurityDisclosureEventModel.objects.count() == 0


def test_direct_model_and_bulk_insert_bypass_are_blocked() -> None:
    with pytest.raises(DjangoValidationError, match="exact append claim"):
        SecurityDisclosureEventModel().save()
    with pytest.raises(DjangoValidationError, match="repository persistence"):
        SecurityDisclosureEventModel.objects.bulk_create([SecurityDisclosureEventModel()])


def test_unknown_source_type_is_retained_without_dispatch_side_effects() -> None:
    event = _event(event_type=SecurityDisclosureEventType.UNKNOWN)
    result = AppendSecurityDisclosureEventUseCase(_repository()).execute(event, BODY_V1)

    assert result.record.event.event_type is SecurityDisclosureEventType.UNKNOWN
    assert result.record.event.raw_event_type == "利润分配预案"
    assert SecurityDisclosureEventModel.objects.count() == 1


def test_listing_coverage_persists_exact_manifest_and_returns_complete_historical_window() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(source_event_id=LISTED_DOCUMENT_ID), BODY_V1
    )

    stored = SecurityDisclosureListingCoverageModel.objects.get()
    result = _listing_query().execute(_listing_scope())

    assert stored.asset_code == "301237.SZ"
    assert stored.start_on == proof.start_on
    assert stored.end_on == proof.end_on
    assert stored.announcement_count == 1
    assert stored.listing_entries[0]["listing_id"] == proof.entries[0].listing_id
    assert stored.listing_entries[0]["source_document_id"] == LISTED_DOCUMENT_ID
    assert stored.first_pass_page_body_sha256 == ["a" * 64]
    assert stored.second_pass_page_body_sha256 == ["b" * 64]
    assert stored.manifest_sha256 == proof.source_manifest_sha256
    assert stored.coverage_manifest_sha256 == proof.coverage_manifest_sha256
    assert stored.first_observed_at == FIRST_SEEN_V1
    assert stored.verified_at == FIRST_SEEN_V1 + timedelta(seconds=10)
    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.COMPLETE
    assert result.source_scope_sha256 == proof.coverage_manifest_sha256
    assert result.proof is not None
    assert result.proof.recorded_at == result.scope.as_of
    assert [item.event.source_event_id for item in result.events] == [LISTED_DOCUMENT_ID]


def test_listing_coverage_is_unavailable_before_observation_or_for_another_window() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    query = _listing_query()

    before = query.execute(_listing_scope(as_of=FIRST_SEEN_V1 - timedelta(seconds=1)))
    different_window = query.execute(_listing_scope(start_on=date(2026, 9, 2)))

    assert before.coverage_status is SecurityDisclosureListingCoverageStatus.MISSING
    assert before.proof is None
    assert before.source_scope_sha256 is None
    assert different_window.coverage_status is SecurityDisclosureListingCoverageStatus.MISSING


def test_listing_coverage_is_not_retroactive_before_durable_persistence() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)

    result = _listing_query().execute(_listing_scope(as_of=proof.verified_at))

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.MISSING
    assert result.reason_code == "LISTING_PROOF_NOT_KNOWN_AT_CUTOFF"
    assert result.proof is None


def test_listing_coverage_expires_after_its_exact_durable_knowledge_cutoff() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)

    result = _listing_query(now=REPOSITORY_NOW + timedelta(seconds=2)).execute(
        _listing_scope(as_of=REPOSITORY_NOW + timedelta(seconds=1))
    )

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert result.reason_code == "LISTING_PROOF_OUTSIDE_EXACT_KNOWN_CUTOFF"
    assert result.proof is not None
    assert result.proof.proof.verified_at == proof.verified_at


def test_listing_coverage_stays_partial_when_any_listed_pdf_is_unrepresented() -> None:
    entries = (
        _listing_entry(
            LISTED_DOCUMENT_ID,
            listing_id="c4c48ea5-7ebd-4e0d-a40b-ffe0d5df0001",
        ),
        _listing_entry(
            SECOND_LISTED_DOCUMENT_ID,
            listing_id="c4c48ea5-7ebd-4e0d-a40b-ffe0d5df0002",
            announcement_id=1225572158,
        ),
    )
    proof = _listing_proof(entries=entries)
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(source_event_id=LISTED_DOCUMENT_ID), BODY_V1
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.PARTIAL
    assert result.reason_code == "LISTED_EVENT_NOT_REPRESENTED"


def test_eleven_row_window_with_only_three_distribution_facts_stays_partial_on_replay() -> None:
    entries = tuple(
        _listing_entry(
            str(UUID(int=0xAB89C4F0E32E4F9AA8BFFF7C1A500000 + index)),
            listing_id=str(UUID(int=0xC4C48EA57EBD4E0DA40BFFE0D5DF0000 + index)),
            announcement_id=1225572157 + index,
            title=(
                f"一心堂：2026年中期权益分派实施公告 {index}"
                if index < 4
                else f"一心堂：其他公告 {index}"
            ),
        )
        for index in range(1, 12)
    )
    proof = _listing_proof(entries=entries)
    _append_listing_proof(proof)
    event_use_case = AppendSecurityDisclosureEventUseCase(_repository())
    selected_events = tuple(
        _event(source_event_id=entry.source_document_id, revision=f"rev-{index}")
        for index, entry in enumerate(entries[:3], start=1)
    )
    for event in selected_events:
        event_use_case.execute(event, BODY_V1)

    first_read = _listing_query().execute(_listing_scope())
    replayed_proof = _append_listing_proof(proof)
    replayed_events = tuple(event_use_case.execute(event, BODY_V1) for event in selected_events)
    second_read = _listing_query().execute(_listing_scope())

    assert replayed_proof.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
    assert all(
        item.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
        for item in replayed_events
    )
    assert first_read.coverage_status is SecurityDisclosureListingCoverageStatus.PARTIAL
    assert second_read.coverage_status is SecurityDisclosureListingCoverageStatus.PARTIAL
    assert len(second_read.events) == 3


def test_listing_coverage_is_unknown_for_unknown_classification_or_unlisted_event() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(
            event_type=SecurityDisclosureEventType.UNKNOWN,
            source_event_id=LISTED_DOCUMENT_ID,
        ),
        BODY_V1,
    )

    unknown = _listing_query().execute(_listing_scope())
    assert unknown.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert unknown.reason_code == "LISTED_EVENT_CLASSIFICATION_UNKNOWN"


def test_listing_coverage_rejects_multiple_revisions_without_qualified_identity() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    event_use_case = AppendSecurityDisclosureEventUseCase(_repository())
    event_use_case.execute(_event(source_event_id=LISTED_DOCUMENT_ID), BODY_V1)
    event_use_case.execute(
        _event(
            body=BODY_V2,
            revision="rev-2",
            source_event_id=LISTED_DOCUMENT_ID,
            first_seen_at=FIRST_SEEN_V1 + timedelta(seconds=1),
        ),
        BODY_V2,
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert result.reason_code == "LISTED_DOCUMENT_REVISION_AMBIGUOUS"


@pytest.mark.parametrize(
    ("source_url", "announced_at"),
    [
        (
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-30/other.pdf",
            date(2026, 9, 30),
        ),
        (None, date(2026, 9, 29)),
    ],
)
def test_listing_coverage_rejects_mismatched_row_url_or_date(
    source_url: str | None,
    announced_at: date,
) -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(
            source_event_id=LISTED_DOCUMENT_ID,
            source_url=source_url,
            announced_at=announced_at,
        ),
        BODY_V1,
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert result.reason_code == "LISTED_EVENT_IDENTITY_MISMATCH"


@pytest.mark.parametrize("announced_at", [date(2026, 9, 29), None])
def test_listing_coverage_is_unknown_for_an_unlisted_event(
    announced_at: date | None,
) -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(body=BODY_V2, source_event_id="unlisted-doc", announced_at=announced_at),
        BODY_V2,
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert result.reason_code == "EVENT_NOT_IN_LISTING_MANIFEST"


def test_unlisted_datetime_near_window_boundary_stays_unknown() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(source_event_id=LISTED_DOCUMENT_ID),
        BODY_V1,
    )
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(
            body=BODY_V2,
            source_event_id="unlisted-datetime-doc",
            announced_at=datetime(2026, 8, 31, 23, 30, tzinfo=UTC),
        ),
        BODY_V2,
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.UNKNOWN
    assert result.reason_code == "EVENT_NOT_IN_LISTING_MANIFEST"


def test_far_unlisted_datetime_does_not_poison_an_exact_window() -> None:
    proof = _listing_proof()
    _append_listing_proof(proof)
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(source_event_id=LISTED_DOCUMENT_ID),
        BODY_V1,
    )
    AppendSecurityDisclosureEventUseCase(_repository()).execute(
        _event(
            body=BODY_V2,
            source_event_id="far-unlisted-datetime-doc",
            announced_at=datetime(2026, 8, 30, 23, 30, tzinfo=UTC),
        ),
        BODY_V2,
    )

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.COMPLETE
    assert result.reason_code == "LISTING_WINDOW_COMPLETE"


def test_listing_coverage_is_idempotent_per_verification_episode() -> None:
    proof = _listing_proof()
    first = _append_listing_proof(proof)
    replay = _append_listing_proof(proof)
    later_episode = replace(
        proof,
        first_observed_at=FIRST_SEEN_V2,
        verified_at=FIRST_SEEN_V2 + timedelta(seconds=10),
    )
    reverified = _append_listing_proof(later_episode)

    assert first.record.proof.first_observed_at == FIRST_SEEN_V1
    assert replay.disposition is SecurityDisclosureEventAppendDisposition.DUPLICATE
    assert replay.record.proof.first_observed_at == FIRST_SEEN_V1
    assert reverified.disposition is SecurityDisclosureEventAppendDisposition.STORED
    assert reverified.record.proof.first_observed_at == FIRST_SEEN_V2
    assert SecurityDisclosureListingCoverageModel.objects.count() == 2


def test_empty_listing_window_requires_and_preserves_an_exact_page_proof() -> None:
    proof = _listing_proof(entries=())
    assert proof.announcement_count == 0
    _append_listing_proof(proof)

    result = _listing_query().execute(_listing_scope())

    assert result.coverage_status is SecurityDisclosureListingCoverageStatus.COMPLETE
    assert result.proof is not None
    assert result.proof.proof.announcement_count == 0
    assert result.events == ()


def test_listing_proof_rejects_duplicate_announcement_ids() -> None:
    entries = (
        _listing_entry(
            LISTED_DOCUMENT_ID,
            listing_id="c4c48ea5-7ebd-4e0d-a40b-ffe0d5df0001",
        ),
        _listing_entry(
            SECOND_LISTED_DOCUMENT_ID,
            listing_id="c4c48ea5-7ebd-4e0d-a40b-ffe0d5df0002",
        ),
    )

    with pytest.raises(ValueError, match="unique listing, announcement, and PDF IDs"):
        _listing_proof(entries=entries)
