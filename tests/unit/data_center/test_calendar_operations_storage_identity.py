"""Independent storage-UUID compatibility for the operation confirmation wrapper."""

from dataclasses import replace
from typing import cast
from uuid import uuid4

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarFormalPublicationPort,
    CalendarPublicationPreparationPort,
    ConfirmCalendarPublicationUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
)
from tests.unit.data_center.test_calendar_publication_operations import (
    NOW,
    FixedClock,
    Publisher,
    _make_preview,
)


class _AssignStorageIds(Publisher):
    """Model the real repository assigning persisted IDs after preparation."""

    def execute(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        commit = super().execute(request, principal=principal)
        reference = commit.record.seal.member_reference
        assigned = replace(
            reference.member,
            member_id=str(uuid4()),
            publication_id=commit.record.publication_id,
        )
        seal = replace(
            commit.record.seal,
            member_reference=replace(reference, member=assigned),
        )
        return replace(commit, record=replace(commit.record, seal=seal))


def test_confirmation_accepts_the_formal_publishers_assigned_storage_ids() -> None:
    """Storage-only UUID assignment preserves all approved source/catalog evidence."""

    preview, reader, principal = _make_preview()
    publisher = _AssignStorageIds()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )

    result = use_case.execute(
        preview.confirmation_intent(),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )

    proposed = publisher.requests[0].proposed_seal
    assert result.record.seal.member_reference.member.member_id != (
        proposed.member_reference.member.member_id
    )
    assert result.record.seal.member_reference.member.publication_id == result.record.publication_id
    assert result.record.seal.publication_hash == preview.expected_publication_hash
