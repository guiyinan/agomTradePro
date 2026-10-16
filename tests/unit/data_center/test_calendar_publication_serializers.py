"""Strict JSON boundary tests for calendar publication operations."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from apps.data_center.application.calendar_publication_operations import (
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
    ReadCurrentCalendarIntent,
)
from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarPublicationPointerExpectation,
)
from apps.data_center.interface.calendar_publication_serializers import (
    CaptureCalendarSnapshotInputSerializer,
    ConfirmCalendarPublicationInputSerializer,
    CurrentCalendarQuerySerializer,
    PreviewCalendarPublicationInputSerializer,
)

_HASH = "a" * 64
_PREFIXED_HASH = f"sha256:{_HASH}"
_SNAPSHOT_ID = "0c68c0aa-3150-45fd-b71e-0c95bf5b4e0b"
_RAW_ID = "f7694367-1956-4916-83ef-4a30a7994840"
_POINTER_ID = "18a02bcb-0701-4586-9b41-e4b2b82b2248"
_PUBLICATION_ID = "dfb40a28-d727-40cf-8906-1917e9a849fb"


def _reference_payload() -> dict[str, object]:
    """Return one complete persisted-source reference payload."""

    return {
        "snapshot_id": _SNAPSHOT_ID,
        "exchange": "SSE",
        "coverage_start": "2026-10-01",
        "coverage_end": "2026-10-30",
        "content_hash": _PREFIXED_HASH,
        "record_digest": _PREFIXED_HASH,
        "raw_payload_id": _RAW_ID,
        "raw_payload_hash": _PREFIXED_HASH,
        "raw_record_digest": _PREFIXED_HASH,
    }


def _identity_payload() -> dict[str, object]:
    """Return every catalog identity field required by confirmation."""

    return {
        "dataset_key": "tushare.exchange_calendar.raw",
        "contract_version": "1.0",
        "schema_version": "1.0",
        "policy_identity": "exchange-calendar-publication",
        "policy_version": "1",
        "calendar_response_max_age_seconds": 3600,
    }


def _absent_pointer_payload() -> dict[str, object]:
    """Return a complete absent current-pointer CAS token."""

    return {
        "dataset_key": "tushare.exchange_calendar.raw",
        "publication_key": "exchange-calendar:SSE",
        "pointer_id": None,
        "publication_id": None,
        "publication_hash": None,
        "activation_id": None,
        "updated_at": None,
    }


def _present_pointer_payload() -> dict[str, object]:
    """Return a complete present pointer CAS token."""

    return {
        "dataset_key": "tushare.exchange_calendar.raw",
        "publication_key": "exchange-calendar:SSE",
        "pointer_id": _POINTER_ID,
        "publication_id": _PUBLICATION_ID,
        "publication_hash": _HASH,
        "activation_id": "calendar-activation:old",
        "updated_at": "2026-10-16T04:00:00Z",
    }


def _preview_payload() -> dict[str, object]:
    """Return the exact machine echo shape exposed by a preview."""

    return {
        "snapshot_reference": _reference_payload(),
        "expected_identity": _identity_payload(),
        "expected_pointer": _absent_pointer_payload(),
        "activation_id": "calendar-activation:next",
        "expected_publication_hash": _HASH,
        "preview_hash": _HASH,
    }


def _serializer_payload(payload: dict[str, object], key: str, value: object) -> dict[str, object]:
    """Make a top-level copy with one changed value for negative cases."""

    return {**payload, key: value}


def test_capture_input_converts_exact_scope_to_typed_intent() -> None:
    """Capture accepts only an explicit exchange and a full ordered date range."""

    serializer = CaptureCalendarSnapshotInputSerializer(
        data={
            "exchange": "SSE",
            "coverage_start": "2026-10-01",
            "coverage_end": "2026-10-30",
        }
    )
    assert serializer.is_valid(), serializer.errors

    intent = serializer.to_intent()

    assert type(intent) is CaptureExchangeCalendarSnapshotIntent
    assert intent.exchange == "SSE"
    assert intent.coverage_start == date(2026, 10, 1)
    assert intent.coverage_end == date(2026, 10, 30)


@pytest.mark.parametrize(
    "extra_key",
    ("actor_id", "user_id", "alias", "database_alias", "ttl", "seal", "credential", "as_of"),
)
def test_capture_rejects_privileged_or_unrelated_extra_fields(extra_key: str) -> None:
    """The HTTP body cannot choose actor, storage, TTL, credentials, or clock."""

    payload: dict[str, object] = {
        "exchange": "SSE",
        "coverage_start": "2026-10-01",
        "coverage_end": "2026-10-30",
        extra_key: "must-not-be-accepted",
    }
    serializer = CaptureCalendarSnapshotInputSerializer(data=payload)

    assert not serializer.is_valid()


@pytest.mark.parametrize(
    "payload",
    (
        {"exchange": 1, "coverage_start": "2026-10-01", "coverage_end": "2026-10-30"},
        {"exchange": True, "coverage_start": "2026-10-01", "coverage_end": "2026-10-30"},
        {"exchange": " SSE", "coverage_start": "2026-10-01", "coverage_end": "2026-10-30"},
        {"exchange": "SSE", "coverage_start": date(2026, 10, 1), "coverage_end": "2026-10-30"},
        {"exchange": "SSE", "coverage_start": "2026-10-30", "coverage_end": "2026-10-01"},
        ["SSE", "2026-10-01", "2026-10-30"],
    ),
)
def test_capture_rejects_coercion_and_invalid_date_ranges(payload: object) -> None:
    """Strings and dates are never silently normalized or accepted out of order."""

    serializer = CaptureCalendarSnapshotInputSerializer(data=payload)

    assert not serializer.is_valid()


def test_preview_input_builds_exact_source_reference() -> None:
    """Preview requires all snapshot and raw-body hashes as one typed reference."""

    serializer = PreviewCalendarPublicationInputSerializer(
        data={"snapshot_reference": _reference_payload()}
    )
    assert serializer.is_valid(), serializer.errors

    intent = serializer.to_intent()

    assert type(intent) is PreviewCalendarPublicationIntent
    assert intent.snapshot_reference.snapshot_id == _SNAPSHOT_ID
    assert intent.snapshot_reference.raw_payload_id == _RAW_ID
    assert intent.snapshot_reference.content_hash == _PREFIXED_HASH


def test_preview_rejects_missing_reference_identity_and_nested_extras() -> None:
    """A partial reference or a nested body field cannot select another source row."""

    incomplete = _reference_payload()
    del incomplete["raw_record_digest"]
    serializer = PreviewCalendarPublicationInputSerializer(data={"snapshot_reference": incomplete})
    assert not serializer.is_valid()

    extra = {**_reference_payload(), "credential": "secret"}
    serializer = PreviewCalendarPublicationInputSerializer(data={"snapshot_reference": extra})
    assert not serializer.is_valid()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("snapshot_id", "0C68C0AA-3150-45FD-B71E-0C95BF5B4E0B"),
        ("content_hash", _HASH),
        ("record_digest", "sha256:" + "A" * 64),
        ("coverage_start", "2026-10-01T00:00:00Z"),
        ("exchange", True),
    ),
)
def test_preview_rejects_noncanonical_reference_values(field: str, value: object) -> None:
    """Reference JSON keeps canonical UUID, digest, date, and text types."""

    reference = _serializer_payload(_reference_payload(), field, value)
    serializer = PreviewCalendarPublicationInputSerializer(data={"snapshot_reference": reference})

    assert not serializer.is_valid()


def test_confirmation_reconstructs_complete_typed_machine_echo() -> None:
    """Confirmation preserves every preview identity and original pointer CAS field."""

    serializer = ConfirmCalendarPublicationInputSerializer(data=_preview_payload())
    assert serializer.is_valid(), serializer.errors

    intent = serializer.to_intent()

    assert type(intent) is ConfirmCalendarPublicationIntent
    assert intent.expected_identity.calendar_response_max_age_seconds == 3600
    assert intent.expected_pointer == CalendarPublicationPointerExpectation(
        dataset_key="tushare.exchange_calendar.raw",
        publication_key="exchange-calendar:SSE",
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    assert intent.snapshot_reference.snapshot_id == _SNAPSHOT_ID
    assert intent.preview_hash == _HASH


@pytest.mark.parametrize(
    "extra_key",
    ("actor_id", "user_id", "alias", "database_alias", "ttl", "seal", "credential", "as_of"),
)
def test_confirmation_rejects_unpreviewed_extra_fields(extra_key: str) -> None:
    """Confirmation accepts only the fields emitted by the preview echo contract."""

    serializer = ConfirmCalendarPublicationInputSerializer(
        data=_serializer_payload(_preview_payload(), extra_key, "not-allowed")
    )

    assert not serializer.is_valid()


def test_confirmation_rejects_nested_extras_partial_cas_and_wrong_json_types() -> None:
    """Nested CAS and identity values use exact JSON types and closed key sets."""

    nested_extra = _preview_payload()
    nested_extra["expected_identity"] = {**_identity_payload(), "ttl_override": 10}
    assert not ConfirmCalendarPublicationInputSerializer(data=nested_extra).is_valid()

    partial_pointer = _preview_payload()
    partial_pointer["expected_pointer"] = {
        **_absent_pointer_payload(),
        "pointer_id": _POINTER_ID,
    }
    assert not ConfirmCalendarPublicationInputSerializer(data=partial_pointer).is_valid()

    bool_ttl = _preview_payload()
    bool_ttl["expected_identity"] = {
        **_identity_payload(),
        "calendar_response_max_age_seconds": True,
    }
    assert not ConfirmCalendarPublicationInputSerializer(data=bool_ttl).is_valid()

    float_ttl = _preview_payload()
    float_ttl["expected_identity"] = {
        **_identity_payload(),
        "calendar_response_max_age_seconds": 3600.0,
    }
    assert not ConfirmCalendarPublicationInputSerializer(data=float_ttl).is_valid()


@pytest.mark.parametrize(
    "timestamp",
    (
        "2026-10-16T04:00:00",
        "2026-10-16T12:00:00+08:00",
        "2026-10-16",
        datetime(2026, 10, 16, 4, 0, tzinfo=UTC),
    ),
)
def test_confirmation_rejects_naive_or_non_utc_pointer_timestamps(timestamp: object) -> None:
    """A pointer timestamp must be an explicit UTC instant from the preview."""

    payload = _preview_payload()
    payload["expected_pointer"] = {
        **_present_pointer_payload(),
        "updated_at": timestamp,
    }

    assert not ConfirmCalendarPublicationInputSerializer(data=payload).is_valid()


def test_confirmation_accepts_complete_present_pointer_cas() -> None:
    """A published current-pointer token is accepted only when every field exists."""

    payload = _preview_payload()
    payload["expected_pointer"] = _present_pointer_payload()
    serializer = ConfirmCalendarPublicationInputSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.to_intent().expected_pointer.pointer_id == _POINTER_ID


def test_confirmation_rejects_ttl_bounds_and_prefixed_publication_hash() -> None:
    """TTL is an echo-only integer inside catalog identity, not a caller override."""

    high_ttl = _preview_payload()
    high_ttl["expected_identity"] = {
        **_identity_payload(),
        "calendar_response_max_age_seconds": MAX_CATALOG_TTL_SECONDS + 1,
    }
    assert not ConfirmCalendarPublicationInputSerializer(data=high_ttl).is_valid()

    prefixed = _serializer_payload(_preview_payload(), "expected_publication_hash", _PREFIXED_HASH)
    assert not ConfirmCalendarPublicationInputSerializer(data=prefixed).is_valid()


def test_current_query_converts_only_exact_dataset_and_exchange() -> None:
    """The current-read intent leaves its knowledge cutoff to the server clock."""

    serializer = CurrentCalendarQuerySerializer(
        data={"dataset_key": "tushare.exchange_calendar.raw", "exchange": "SSE"}
    )
    assert serializer.is_valid(), serializer.errors

    query = serializer.to_query()

    assert type(query) is ReadCurrentCalendarIntent
    assert query.dataset_key == "tushare.exchange_calendar.raw"
    assert query.exchange == "SSE"


@pytest.mark.parametrize("extra_key", ("as_of", "using", "database_alias", "actor_id", "ttl"))
def test_current_query_rejects_client_clock_and_internal_selectors(extra_key: str) -> None:
    """Current GET cannot choose a clock, connection alias, actor, or TTL."""

    serializer = CurrentCalendarQuerySerializer(
        data={
            "dataset_key": "tushare.exchange_calendar.raw",
            "exchange": "SSE",
            extra_key: "not-allowed",
        }
    )

    assert not serializer.is_valid()


def test_current_query_rejects_duplicate_parameters_and_coerced_strings() -> None:
    """Duplicate query values and integer-as-text coercion are not ambiguous input."""

    duplicate = QueryDict("dataset_key=calendar&dataset_key=other&exchange=SSE")
    serializer = CurrentCalendarQuerySerializer(data=duplicate)
    assert not serializer.is_valid()

    coerced = CurrentCalendarQuerySerializer(data={"dataset_key": 123, "exchange": "SSE"})
    assert not coerced.is_valid()


def test_explicit_typed_entrypoints_require_successful_validation() -> None:
    """All four public conversion methods return App DTOs only after validation."""

    malformed = CaptureCalendarSnapshotInputSerializer(data={"exchange": "SSE"})
    with pytest.raises(ValidationError):
        malformed.to_intent()

    malformed_preview = PreviewCalendarPublicationInputSerializer(data={})
    with pytest.raises(ValidationError):
        malformed_preview.to_intent()

    malformed_confirm = ConfirmCalendarPublicationInputSerializer(data={})
    with pytest.raises(ValidationError):
        malformed_confirm.to_intent()

    malformed_query = CurrentCalendarQuerySerializer(data={})
    with pytest.raises(ValidationError):
        malformed_query.to_query()


def test_pointer_serializer_requires_explicit_cas_null_fields() -> None:
    """An omitted pointer field cannot be confused with an explicit absent CAS."""

    payload = _preview_payload()
    pointer = _absent_pointer_payload()
    del pointer["updated_at"]
    payload["expected_pointer"] = pointer

    assert not ConfirmCalendarPublicationInputSerializer(data=payload).is_valid()
