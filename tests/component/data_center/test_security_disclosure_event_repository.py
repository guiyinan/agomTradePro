"""SQLite contract for source-bound, append-only official disclosure facts."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.data_center.application.security_disclosure_event import (
    AppendSecurityDisclosureEventUseCase,
    QuerySecurityDisclosureEventsUseCase,
)
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendDisposition,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from apps.data_center.infrastructure.security_disclosure_event_models import (
    SecurityDisclosureEventModel,
)
from apps.data_center.infrastructure.security_disclosure_event_repository import (
    DjangoSecurityDisclosureEventRepository,
)
from core.exceptions import DataValidationError

pytestmark = pytest.mark.django_db

BODY_V1 = b"%PDF-1.7\nsource disclosure version one"
BODY_V2 = b"%PDF-1.7\nsource disclosure corrected version"
FIRST_SEEN_V1 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
FIRST_SEEN_V2 = datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
REPOSITORY_NOW = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)


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
    supersedes_source_event_id: str | None = None,
    supersedes_source_revision_id: str | None = None,
) -> SecurityDisclosureEvent:
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="301237.SZ",
        source_security_code="301237",
        source_event_id="disclose-301237-001",
        source_revision_id=revision,
        raw_event_type="利润分配预案",
        event_type=event_type,
        source_url="https://www.szse.cn/disclosure/listed/bulletinDetail/index.html",
        source_document_body=body,
        first_seen_at=first_seen_at,
        announced_at=announced_at,
        source_available_at=source_available_at,
        effective_at=effective_at,
        supersedes_source_event_id=supersedes_source_event_id,
        supersedes_source_revision_id=supersedes_source_revision_id,
    )


def _repository() -> DjangoSecurityDisclosureEventRepository:
    return DjangoSecurityDisclosureEventRepository(clock=_Clock())


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


def test_pit_cutoff_uses_first_seen_only_and_includes_future_effective_event() -> None:
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
    after_observation = query.execute(
        SecurityDisclosureEventReadScope(
            as_of=FIRST_SEEN_V1,
            exchange=SecurityDisclosureExchange.SZSE,
            asset_code="301237.SZ",
        )
    )

    assert before_observation == ()
    assert len(after_observation) == 1
    assert after_observation[0].event.effective_at == date(2028, 1, 5)


def test_correction_is_available_only_after_its_first_seen_cutoff() -> None:
    repository = _repository()
    append = AppendSecurityDisclosureEventUseCase(repository)
    original = _event()
    correction = _event(
        body=BODY_V2,
        revision="rev-2",
        first_seen_at=FIRST_SEEN_V2,
        announced_at=date(2026, 11, 4),
        supersedes_source_event_id="disclose-301237-001",
        supersedes_source_revision_id="rev-1",
    )
    append.execute(original, BODY_V1)
    append.execute(correction, BODY_V2)
    query = QuerySecurityDisclosureEventsUseCase(repository)

    earlier = query.execute(
        SecurityDisclosureEventReadScope(as_of=datetime(2026, 11, 4, 23, tzinfo=UTC))
    )
    later = query.execute(SecurityDisclosureEventReadScope(as_of=FIRST_SEEN_V2))

    assert [record.event.source_revision_id for record in earlier] == ["rev-1"]
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
