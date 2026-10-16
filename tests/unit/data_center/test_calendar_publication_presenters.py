"""Calendar response contracts preserve typed machine echo and reference scope."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import uuid4

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CapturedExchangeCalendarSnapshot,
    ConfirmCalendarPublicationUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)
from apps.data_center.interface.calendar_publication_presenters import (
    present_calendar_capture,
    present_calendar_commit,
    present_calendar_current,
    present_calendar_preview,
)
from apps.data_center.interface.calendar_publication_serializers import (
    ConfirmCalendarPublicationInputSerializer,
    PreviewCalendarPublicationInputSerializer,
)
from tests.unit.data_center.test_calendar_publication_operations import (
    NOW,
    FixedClock,
    Publisher,
    _context,
    _make_preview,
    _snapshot,
)


def _json_object(value: dict[str, object]) -> dict[str, object]:
    """Require an ordinary JSON object without a custom datetime encoder."""

    result = json.loads(json.dumps(value, allow_nan=False))
    assert type(result) is dict
    return cast(dict[str, object], result)


def _assert_reference_boundary(payload: dict[str, object]) -> None:
    """Do not expose audit browsing, private seals or decision capability."""

    assert payload["must_not_execute"] is True
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "exchange_calendar_reference_only"
    encoded = json.dumps(payload)
    for key in (
        "seal",
        "audit_pair",
        "event_content_hash",
        "outbox_id",
        "actor_user_id",
        "api_key",
        "token",
    ):
        assert f'"{key}"' not in encoded


def test_capture_payload_drives_preview_without_manual_reference_fields() -> None:
    snapshot = _snapshot()
    value = CapturedExchangeCalendarSnapshot(
        snapshot_reference=snapshot.reference(),
        first_seen_at=snapshot.first_seen_at,
        recorded_at=snapshot.recorded_at,
        source_published_at=None,
    )
    payload = _json_object(present_calendar_capture(value))
    _assert_reference_boundary(payload)
    assert payload["publication_status"] == "unpublished"
    assert payload["source_published_at"] is None
    assert payload["first_seen_at"] == snapshot.first_seen_at.isoformat().replace("+00:00", "Z")
    serializer = PreviewCalendarPublicationInputSerializer(data=payload["preview_intent"])
    assert serializer.is_valid(), serializer.errors
    assert serializer.to_intent().snapshot_reference == snapshot.reference()


def test_preview_payload_roundtrips_the_entire_absent_pointer_confirmation() -> None:
    preview, _reader, _principal = _make_preview()
    payload = _json_object(present_calendar_preview(preview))
    _assert_reference_boundary(payload)
    assert payload["previewed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert payload["response_expires_at"] == preview.response_expires_at.isoformat().replace(
        "+00:00", "Z"
    )
    serializer = ConfirmCalendarPublicationInputSerializer(data=payload["confirmation_intent"])
    assert serializer.is_valid(), serializer.errors
    assert serializer.to_intent() == preview.confirmation_intent()


def test_preview_payload_roundtrips_all_existing_pointer_cas_fields() -> None:
    context = _context()
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=context.contract.key.value,
        publication_key=context.current_pointer.publication_key,
        pointer_id=str(uuid4()),
        publication_id=str(uuid4()),
        publication_hash="f" * 64,
        activation_id="previous-activation",
        updated_at=NOW - timedelta(seconds=1),
    )
    preview, _reader, _principal = _make_preview(replace(context, current_pointer=pointer))
    payload = _json_object(present_calendar_preview(preview))
    serializer = ConfirmCalendarPublicationInputSerializer(data=payload["confirmation_intent"])
    assert serializer.is_valid(), serializer.errors
    assert serializer.to_intent().expected_pointer == pointer


def test_commit_and_current_payloads_keep_source_clocks_and_reference_days() -> None:
    preview, reader, principal = _make_preview()
    commit = ConfirmCalendarPublicationUseCase(
        preparation=reader, publisher=Publisher(), clock=FixedClock(NOW)
    ).execute(
        preview.confirmation_intent(),
        principal=cast(LockedCalendarPublisherPrincipal, principal),
    )
    receipt = _json_object(present_calendar_commit(commit))
    _assert_reference_boundary(receipt)
    assert receipt["transition"] == commit.transition.value
    publication = cast(dict[str, object], receipt["publication"])
    assert publication["publication_id"] == commit.record.publication_id
    assert publication["published_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert publication["source_published_at"] is None
    current = CurrentPublishedExchangeCalendar(
        record=commit.record, pointer=commit.pointer, as_of=NOW + timedelta(seconds=2)
    )
    payload = _json_object(present_calendar_current(current))
    _assert_reference_boundary(payload)
    assert payload["as_of"] == current.as_of.isoformat().replace("+00:00", "Z")
    assert payload["calendar_days"] == [
        day.to_payload() for day in current.record.seal.snapshot.days
    ]
    assert payload["publication"] == publication
