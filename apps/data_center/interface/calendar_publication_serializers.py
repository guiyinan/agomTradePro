"""Strict JSON adapters for the four-step exchange-calendar workflow."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID

from django.http import QueryDict
from rest_framework import serializers

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreviewIdentity,
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    PreviewCalendarPublicationIntent,
    ReadCurrentCalendarIntent,
)
from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarPublicationPointerExpectation,
)

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_PREFIXED_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,299}\Z")
_UTC_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")


class _StrictSerializer(serializers.Serializer[dict[str, object]]):
    """Reject non-object input, unknown keys, and repeated query parameters."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Narrow a JSON object before DRF field conversion can ignore extras."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected a JSON object.")
        raw_keys = tuple(data.keys())
        if any(type(key) is not str for key in raw_keys):
            raise serializers.ValidationError("Object keys must be strings.")
        unknown = sorted(set(cast(tuple[str, ...], raw_keys)) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown)}"]}
            )
        if isinstance(data, QueryDict):
            repeated = sorted(key for key in data.keys() if len(data.getlist(key)) != 1)
            if repeated:
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Repeated query parameters: {', '.join(repeated)}"]}
                )
        return cast(dict[str, object], super().to_internal_value(data))


class _ExactStringField(serializers.CharField):
    """Accept JSON strings only and never trim caller input."""

    def __init__(
        self,
        *,
        max_length: int | None = None,
        min_length: int | None = None,
        allow_null: bool = False,
    ) -> None:
        """Configure a non-coercing, non-trimming string field."""

        super().__init__(
            max_length=max_length,
            min_length=min_length,
            allow_blank=False,
            allow_null=allow_null,
            required=True,
            trim_whitespace=False,
        )

    def to_internal_value(self, data: object) -> str:
        """Reject integer, boolean, or other Python values before CharField coercion."""

        if type(data) is not str:
            raise serializers.ValidationError("Expected a string.")
        value = super().to_internal_value(data)
        if value.strip() != value:
            raise serializers.ValidationError("Whitespace padding is not accepted.")
        return value


class _CanonicalUuidField(_ExactStringField):
    """Accept only lowercase canonical UUID strings."""

    def to_internal_value(self, data: object) -> str:
        """Validate the canonical spelling without normalizing it."""

        value = super().to_internal_value(data)
        if _UUID_RE.fullmatch(value) is None:
            raise serializers.ValidationError("Expected a canonical UUID.")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise serializers.ValidationError("Expected a canonical UUID.") from error
        if str(parsed) != value:
            raise serializers.ValidationError("Expected a canonical UUID.")
        return value


class _PrefixedSha256Field(_ExactStringField):
    """Accept the prefixed digest representation used by calendar references."""

    def to_internal_value(self, data: object) -> str:
        """Reject non-canonical or unprefixed digest text."""

        value = super().to_internal_value(data)
        if _PREFIXED_SHA256_RE.fullmatch(value) is None:
            raise serializers.ValidationError("Expected a lowercase sha256 digest.")
        return value


class _Sha256Field(_ExactStringField):
    """Accept an unprefixed lowercase digest used by publication operations."""

    def to_internal_value(self, data: object) -> str:
        """Reject prefixes, uppercase hex, or invalid digest lengths."""

        value = super().to_internal_value(data)
        if _SHA256_RE.fullmatch(value) is None:
            raise serializers.ValidationError("Expected a lowercase SHA-256 digest.")
        return value


class _ActivationIdField(_ExactStringField):
    """Accept the bounded token format used for calendar activation identities."""

    def to_internal_value(self, data: object) -> str:
        """Reject whitespace and punctuation outside the application contract."""

        value = super().to_internal_value(data)
        if _TOKEN_RE.fullmatch(value) is None:
            raise serializers.ValidationError("Expected a bounded activation token.")
        return value


class _ExactDateField(serializers.DateField):
    """Accept only canonical ``YYYY-MM-DD`` JSON strings."""

    def to_internal_value(self, data: object) -> date:
        """Reject date objects, datetimes, and alternate date spellings."""

        if type(data) is not str:
            raise serializers.ValidationError("Expected an ISO calendar date string.")
        try:
            parsed = date.fromisoformat(data)
        except ValueError as error:
            raise serializers.ValidationError("Expected an ISO calendar date string.") from error
        if parsed.isoformat() != data:
            raise serializers.ValidationError("Expected an ISO calendar date string.")
        return parsed


class _UtcDateTimeField(serializers.DateTimeField):
    """Accept only explicit, timezone-aware UTC instants."""

    def to_internal_value(self, data: object) -> datetime:
        """Reject naive values and non-UTC offsets without assigning a timezone."""

        if type(data) is not str or _UTC_DATETIME_RE.fullmatch(data) is None:
            raise serializers.ValidationError("Expected a timezone-aware UTC instant.")
        try:
            value = datetime.fromisoformat(data.replace("Z", "+00:00"))
        except ValueError as error:
            raise serializers.ValidationError("Expected a timezone-aware UTC instant.") from error
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise serializers.ValidationError("Expected a timezone-aware UTC instant.")
        return value


class _ExactIntegerField(serializers.IntegerField):
    """Accept actual JSON integers only; booleans and fractional values are invalid."""

    def to_internal_value(self, data: object) -> int:
        """Reject values that DRF's default integer field would coerce."""

        if type(data) is not int:
            raise serializers.ValidationError("Expected an integer.")
        return super().to_internal_value(data)


class _SnapshotReferenceSerializer(_StrictSerializer):
    """Validate the complete persisted snapshot and raw-source reference."""

    snapshot_id = _CanonicalUuidField()
    exchange = _ExactStringField(max_length=32)
    coverage_start = _ExactDateField()
    coverage_end = _ExactDateField()
    content_hash = _PrefixedSha256Field()
    record_digest = _PrefixedSha256Field()
    raw_payload_id = _CanonicalUuidField()
    raw_payload_hash = _PrefixedSha256Field()
    raw_record_digest = _PrefixedSha256Field()


class _PreviewIdentitySerializer(_StrictSerializer):
    """Validate the complete catalog and calendar TTL identity echo."""

    dataset_key = _ExactStringField(max_length=300)
    contract_version = _ExactStringField(max_length=300)
    schema_version = _ExactStringField(max_length=300)
    policy_identity = _ExactStringField(max_length=300)
    policy_version = _ExactStringField(max_length=300)
    calendar_response_max_age_seconds = _ExactIntegerField(
        min_value=1,
        max_value=MAX_CATALOG_TTL_SECONDS,
    )


class _PointerExpectationSerializer(_StrictSerializer):
    """Validate the complete current-pointer compare-and-swap identity."""

    dataset_key = _ExactStringField(max_length=160)
    publication_key = _ExactStringField(max_length=300)
    pointer_id = _CanonicalUuidField(allow_null=True)
    publication_id = _CanonicalUuidField(allow_null=True)
    publication_hash = _Sha256Field(allow_null=True)
    activation_id = _ActivationIdField(allow_null=True)
    updated_at = _UtcDateTimeField(allow_null=True)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require the absent CAS to be wholly null or the present CAS complete."""

        echo_keys = (
            "pointer_id",
            "publication_id",
            "publication_hash",
            "activation_id",
            "updated_at",
        )
        present = tuple(key for key in echo_keys if attrs.get(key) is not None)
        if present and len(present) != len(echo_keys):
            raise serializers.ValidationError(
                {"non_field_errors": ["Pointer identity must be wholly absent or fully bound."]}
            )
        return attrs


class CaptureCalendarSnapshotInputSerializer(_StrictSerializer):
    """Validate a request to capture one complete source calendar range."""

    exchange = _ExactStringField(max_length=32)
    coverage_start = _ExactDateField()
    coverage_end = _ExactDateField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Reject inverted date ranges before making an Application intent."""

        start = cast(date, attrs["coverage_start"])
        end = cast(date, attrs["coverage_end"])
        if start > end:
            raise serializers.ValidationError(
                {"coverage_start": ["coverage_start must not follow coverage_end."]}
            )
        return attrs

    def to_intent(self) -> CaptureExchangeCalendarSnapshotIntent:
        """Return the exact typed capture intent after successful validation."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        try:
            return CaptureExchangeCalendarSnapshotIntent(
                exchange=_string(data, "exchange"),
                coverage_start=_date(data, "coverage_start"),
                coverage_end=_date(data, "coverage_end"),
            )
        except CalendarPublicationOperationsError as error:
            raise _as_validation_error(error) from error


class PreviewCalendarPublicationInputSerializer(_StrictSerializer):
    """Validate an exact saved snapshot reference for preview."""

    snapshot_reference = _SnapshotReferenceSerializer()

    def to_intent(self) -> PreviewCalendarPublicationIntent:
        """Return a typed preview intent bound to the complete raw-source reference."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        reference_payload = _mapping(data, "snapshot_reference")
        try:
            reference = _snapshot_reference(reference_payload)
            return PreviewCalendarPublicationIntent(snapshot_reference=reference)
        except (CalendarPublicationOperationsError, ExchangeCalendarError) as error:
            raise _as_validation_error(error) from error


class ConfirmCalendarPublicationInputSerializer(_StrictSerializer):
    """Validate the exact preview echo required for publication confirmation."""

    snapshot_reference = _SnapshotReferenceSerializer()
    expected_identity = _PreviewIdentitySerializer()
    expected_pointer = _PointerExpectationSerializer()
    activation_id = _ActivationIdField()
    expected_publication_hash = _Sha256Field()
    preview_hash = _Sha256Field()

    def to_intent(self) -> ConfirmCalendarPublicationIntent:
        """Return the exact typed echo; no caller-supplied seal or clock is accepted."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        try:
            return ConfirmCalendarPublicationIntent(
                snapshot_reference=_snapshot_reference(_mapping(data, "snapshot_reference")),
                expected_identity=_preview_identity(_mapping(data, "expected_identity")),
                expected_pointer=_pointer_expectation(_mapping(data, "expected_pointer")),
                activation_id=_string(data, "activation_id"),
                expected_publication_hash=_string(data, "expected_publication_hash"),
                preview_hash=_string(data, "preview_hash"),
            )
        except (
            CalendarFormalPublicationError,
            CalendarPublicationOperationsError,
            ExchangeCalendarError,
        ) as error:
            raise _as_validation_error(error) from error


class CurrentCalendarQuerySerializer(_StrictSerializer):
    """Validate an exact current-read scope without a client-controlled cutoff."""

    dataset_key = _ExactStringField(max_length=160)
    exchange = _ExactStringField(max_length=32)

    def to_query(self) -> ReadCurrentCalendarIntent:
        """Return a server-clocked current-read intent for one dataset and exchange."""

        self.is_valid(raise_exception=True)
        data = cast(dict[str, object], self.validated_data)
        try:
            return ReadCurrentCalendarIntent(
                dataset_key=_string(data, "dataset_key"),
                exchange=_string(data, "exchange"),
            )
        except CalendarPublicationOperationsError as error:
            raise _as_validation_error(error) from error


def _snapshot_reference(data: Mapping[str, object]) -> ExchangeCalendarSnapshotReference:
    """Build one reference only from all validated source and digest fields."""

    reference = ExchangeCalendarSnapshotReference(
        snapshot_id=_string(data, "snapshot_id"),
        exchange=_string(data, "exchange"),
        coverage_start=_date(data, "coverage_start"),
        coverage_end=_date(data, "coverage_end"),
        content_hash=_string(data, "content_hash"),
        record_digest=_string(data, "record_digest"),
        raw_payload_id=_string(data, "raw_payload_id"),
        raw_payload_hash=_string(data, "raw_payload_hash"),
        raw_record_digest=_string(data, "raw_record_digest"),
    )
    reference.__post_init__()
    return reference


def _preview_identity(data: Mapping[str, object]) -> CalendarPublicationPreviewIdentity:
    """Build the complete typed preview identity, including its echoed TTL."""

    identity = CalendarPublicationPreviewIdentity(
        dataset_key=_string(data, "dataset_key"),
        contract_version=_string(data, "contract_version"),
        schema_version=_string(data, "schema_version"),
        policy_identity=_string(data, "policy_identity"),
        policy_version=_string(data, "policy_version"),
        calendar_response_max_age_seconds=_integer(data, "calendar_response_max_age_seconds"),
    )
    identity.__post_init__()
    return identity


def _pointer_expectation(data: Mapping[str, object]) -> CalendarPublicationPointerExpectation:
    """Build a fully validated absent or present compare-and-swap token."""

    pointer = CalendarPublicationPointerExpectation(
        dataset_key=_string(data, "dataset_key"),
        publication_key=_string(data, "publication_key"),
        pointer_id=_optional_string(data, "pointer_id"),
        publication_id=_optional_string(data, "publication_id"),
        publication_hash=_optional_string(data, "publication_hash"),
        activation_id=_optional_string(data, "activation_id"),
        updated_at=_optional_datetime(data, "updated_at"),
    )
    pointer.validate()
    return pointer


def _mapping(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Return one already-validated nested object."""

    value = data.get(key)
    if not isinstance(value, Mapping):
        raise serializers.ValidationError({key: ["Expected an object."]})
    return cast(Mapping[str, object], value)


def _string(data: Mapping[str, object], key: str) -> str:
    """Read one exact string from validated serializer output."""

    value = data.get(key)
    if type(value) is not str:
        raise serializers.ValidationError({key: ["Expected a string."]})
    return value


def _date(data: Mapping[str, object], key: str) -> date:
    """Read one parsed calendar date from validated serializer output."""

    value = data.get(key)
    if type(value) is not date:
        raise serializers.ValidationError({key: ["Expected a calendar date."]})
    return value


def _integer(data: Mapping[str, object], key: str) -> int:
    """Read one exact integer from validated serializer output."""

    value = data.get(key)
    if type(value) is not int:
        raise serializers.ValidationError({key: ["Expected an integer."]})
    return value


def _optional_string(data: Mapping[str, object], key: str) -> str | None:
    """Read one nullable string without coercion."""

    value = data.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise serializers.ValidationError({key: ["Expected a string or null."]})
    return value


def _optional_datetime(data: Mapping[str, object], key: str) -> datetime | None:
    """Read one nullable UTC timestamp without assigning a timezone."""

    value = data.get(key)
    if value is None:
        return None
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise serializers.ValidationError({key: ["Expected an aware UTC instant or null."]})
    return value


def _as_validation_error(error: Exception) -> serializers.ValidationError:
    """Convert recognized domain/Application input failures to HTTP validation errors."""

    code = getattr(error, "code", "CALENDAR_REQUEST_INVALID")
    return serializers.ValidationError({"non_field_errors": [str(code)]})


__all__ = [
    "CaptureCalendarSnapshotInputSerializer",
    "ConfirmCalendarPublicationInputSerializer",
    "CurrentCalendarQuerySerializer",
    "PreviewCalendarPublicationInputSerializer",
]
