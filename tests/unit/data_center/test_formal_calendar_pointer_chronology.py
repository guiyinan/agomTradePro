"""Independent counterexamples for formal calendar pointer chronology."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarFormalPublicationRequest,
    PublishExchangeCalendarSnapshotUseCase,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarPublicationTransition,
    decide_calendar_publication_transition,
    validate_current_calendar_publication,
)
from tests.unit.data_center.test_formal_exchange_calendar_publication import (
    NOW,
    _commit,
    _pointer,
    _Principal,
    _record,
    _seal,
    _Writer,
)


@pytest.mark.parametrize("offset", [-1, 1])
def test_current_read_rejects_pointer_clock_different_from_publication(offset: int) -> None:
    record = _record()
    pointer = replace(_pointer(record), updated_at=record.published_at + timedelta(seconds=offset))

    with pytest.raises(CalendarFormalPublicationError) as caught:
        validate_current_calendar_publication(record, pointer, as_of=NOW)

    assert caught.value.code == "CALENDAR_CURRENT_POINTER_TIME_MISMATCH"


@pytest.mark.parametrize("offset", [-1, 1])
def test_replay_rejects_corrupted_pointer_clock_even_with_matching_cas(offset: int) -> None:
    record = _record()
    pointer = replace(_pointer(record), updated_at=record.published_at + timedelta(seconds=offset))

    with pytest.raises(CalendarFormalPublicationError) as caught:
        decide_calendar_publication_transition(
            proposed_seal=record.seal,
            expected_pointer=pointer,
            actual_pointer=pointer,
            current_record=record,
            activation_id=record.activation_id,
        )

    assert caught.value.code == "CALENDAR_CURRENT_POINTER_TIME_MISMATCH"


@pytest.mark.parametrize("old_pointer_offset", [0, 1])
def test_forward_commit_cannot_publish_at_or_before_old_pointer(old_pointer_offset: int) -> None:
    old_record = _record(published_at=NOW + timedelta(microseconds=old_pointer_offset))
    expected = _pointer(old_record)
    request = CalendarFormalPublicationRequest(
        proposed_seal=_seal(), expected_pointer=expected, activation_id="forward-activation"
    )
    candidate = _commit(request)
    commit = replace(
        candidate,
        pointer=replace(candidate.pointer, pointer_id=expected.pointer_id),
        transition=CalendarPublicationTransition.FORWARD_PUBLISH,
    )
    assert commit.record.publication_id != old_record.publication_id
    assert commit.record.published_at <= expected.updated_at

    with pytest.raises(CalendarFormalPublicationApplicationError) as caught:
        PublishExchangeCalendarSnapshotUseCase(_Writer(commit)).execute(
            request, principal=_Principal()
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_FORWARD_TIME_INVALID"


def test_forward_commit_must_keep_the_existing_pointer_row_identity() -> None:
    previous = _record(published_at=NOW - timedelta(seconds=1))
    request = CalendarFormalPublicationRequest(
        proposed_seal=_seal(),
        expected_pointer=_pointer(previous),
        activation_id="forward-same-pointer-row",
    )
    commit = replace(_commit(request), transition=CalendarPublicationTransition.FORWARD_PUBLISH)
    assert commit.pointer.pointer_id != request.expected_pointer.pointer_id

    with pytest.raises(CalendarFormalPublicationApplicationError) as caught:
        PublishExchangeCalendarSnapshotUseCase(_Writer(commit)).execute(
            request, principal=_Principal()
        )

    assert caught.value.code == "CALENDAR_PUBLICATION_POINTER_BINDING_INVALID"
