"""Original confirmation CAS scope remains binding even for an exact retry."""

from dataclasses import replace
from typing import cast

import pytest

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarFormalPublicationPort,
    CalendarPublicationOperationsError,
    CalendarPublicationPreparationPort,
    ConfirmCalendarPublicationUseCase,
    _preview_hash,
)
from tests.unit.data_center.test_calendar_publication_operations import (
    NOW,
    FixedClock,
    Publisher,
    _make_preview,
)


def test_exact_retry_cannot_replace_the_original_cas_scope_using_an_unkeyed_checksum() -> None:
    """A checksum binds content but cannot legitimize another dataset's CAS tuple."""

    preview, reader, principal = _make_preview()
    publisher = Publisher()
    use_case = ConfirmCalendarPublicationUseCase(
        preparation=cast(CalendarPublicationPreparationPort, reader),
        publisher=cast(CalendarFormalPublicationPort, publisher),
        clock=FixedClock(NOW),
    )
    trusted_principal = cast(LockedCalendarPublisherPrincipal, principal)
    first = use_case.execute(preview.confirmation_intent(), principal=trusted_principal)
    reader.context = replace(reader.context, current_pointer=first.pointer)
    foreign_cas = replace(preview.expected_pointer, dataset_key="another.calendar.dataset")
    # This checksum is intentionally recomputable by any caller. It is not an
    # authorization proof and cannot waive the original CAS scope constraint.
    checksum = _preview_hash(
        reference=preview.snapshot_reference,
        identity=preview.identity,
        pointer=foreign_cas,
        activation_id=preview.activation_id,
        publication_hash=preview.expected_publication_hash,
        first_seen_at=preview.first_seen_at,
        snapshot_recorded_at=preview.snapshot_recorded_at,
        source_published_at=preview.source_published_at,
        response_expires_at=preview.response_expires_at,
    )
    altered = replace(preview, expected_pointer=foreign_cas, preview_hash=checksum)

    with pytest.raises(CalendarPublicationOperationsError) as failure:
        use_case.execute(altered.confirmation_intent(), principal=trusted_principal)

    assert failure.value.code == "CALENDAR_PUBLICATION_POINTER_SCOPE_MISMATCH"
    assert len(publisher.requests) == 1
