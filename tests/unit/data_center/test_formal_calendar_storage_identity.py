"""Storage UUID assignment must preserve the complete calendar evidence seal."""

from dataclasses import replace
from uuid import uuid4

import pytest

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRequest,
    PublishExchangeCalendarSnapshotUseCase,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarPublicationPointerExpectation,
    CalendarPublicationTransition,
    calendar_formal_seals_have_same_evidence,
    decide_calendar_publication_transition,
)
from tests.unit.data_center.test_formal_exchange_calendar_publication import (
    _commit,
    _pointer,
    _Principal,
    _record,
    _seal,
    _Writer,
)


def test_assigning_member_storage_uuids_does_not_turn_current_replay_into_forward() -> None:
    record = _record()
    member = record.seal.member_reference.member
    proposal = replace(
        record.seal,
        member_reference=replace(
            record.seal.member_reference,
            member=replace(member, member_id=str(uuid4()), publication_id=str(uuid4())),
        ),
    )
    pointer = _pointer(record)

    transition = decide_calendar_publication_transition(
        proposed_seal=proposal,
        expected_pointer=pointer,
        actual_pointer=pointer,
        current_record=record,
        activation_id=record.activation_id,
    )

    assert transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY


def test_publisher_accepts_repository_assigned_uuids_with_unchanged_full_evidence() -> None:
    seal = _seal()
    request = CalendarFormalPublicationRequest(
        proposed_seal=seal,
        expected_pointer=CalendarPublicationPointerExpectation(
            dataset_key=seal.dataset.value,
            publication_key=seal.publication_key,
            pointer_id=None,
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        ),
        activation_id="repository-assigned-identity",
    )
    commit = _commit(request)
    stored_member = replace(
        seal.member_reference.member,
        member_id=str(uuid4()),
        publication_id=commit.record.publication_id,
    )
    persisted_seal = replace(
        seal, member_reference=replace(seal.member_reference, member=stored_member)
    )
    result = replace(commit, record=replace(commit.record, seal=persisted_seal))

    actual = PublishExchangeCalendarSnapshotUseCase(_Writer(result)).execute(
        request, principal=_Principal()
    )

    assert actual.record.seal.member_reference.member == stored_member
    assert actual.record.seal.publication_hash == seal.publication_hash


def test_storage_identity_comparison_retains_ttl_and_source_evidence_binding() -> None:
    seal = _seal()
    changed = _seal(snapshot=seal.snapshot, ttl=61)

    assert not calendar_formal_seals_have_same_evidence(seal, changed)


@pytest.mark.parametrize("left_invalid", [True, False])
def test_storage_identity_comparison_rejects_untyped_seals(left_invalid: bool) -> None:
    seal = _seal()
    with pytest.raises(CalendarFormalPublicationError) as caught:
        calendar_formal_seals_have_same_evidence(
            None if left_invalid else seal, seal if left_invalid else None
        )

    assert caught.value.code == "CALENDAR_FORMAL_SEAL_INVALID"
