"""Explicit JSON projections for the calendar operations HTTP and TUI adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationPreview,
    CalendarPublicationPreviewIdentity,
    CapturedExchangeCalendarSnapshot,
    ConfirmCalendarPublicationIntent,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
    CalendarPublicationPointerExpectation,
)


def present_calendar_capture(value: CapturedExchangeCalendarSnapshot) -> dict[str, object]:
    """Present a saved, unpublished reference and its complete next-step input."""

    value.__post_init__()
    return {
        **_reference_boundary("unpublished_source_reference"),
        "publication_status": "unpublished",
        "snapshot_reference": value.snapshot_reference.to_payload(),
        "first_seen_at": _utc_text(value.first_seen_at),
        "recorded_at": _utc_text(value.recorded_at),
        "source_published_at": _optional_utc_text(value.source_published_at),
        "preview_intent": {"snapshot_reference": value.snapshot_reference.to_payload()},
    }


def present_calendar_preview(value: CalendarPublicationPreview) -> dict[str, object]:
    """Present the exact server preview with machine-echoable confirmation data."""

    value.__post_init__()
    return {
        **_reference_boundary("unpublished_publication_preview"),
        "publication_status": "preview",
        "snapshot_reference": value.snapshot_reference.to_payload(),
        "identity": _identity_payload(value.identity),
        "first_seen_at": _utc_text(value.first_seen_at),
        "snapshot_recorded_at": _utc_text(value.snapshot_recorded_at),
        "source_published_at": _optional_utc_text(value.source_published_at),
        "response_expires_at": _utc_text(value.response_expires_at),
        "previewed_at": _utc_text(value.previewed_at),
        "confirmation_intent": _confirmation_payload(value.confirmation_intent()),
    }


def present_calendar_commit(value: CalendarFormalPublicationCommit) -> dict[str, object]:
    """Present a committed publication without exposing the private Audit receipt."""

    value.__post_init__()
    return {
        **_reference_boundary("audited_calendar_reference"),
        "publication_status": "published",
        "transition": value.transition.value,
        "publication": _record_payload(value.record),
        "checked_at": _utc_text(value.post_audit_checked_at),
    }


def present_calendar_current(value: CurrentPublishedExchangeCalendar) -> dict[str, object]:
    """Present exact current reference days and the server-owned validation cutoff."""

    value.__post_init__()
    return {
        **_reference_boundary("audited_calendar_reference"),
        "publication_status": "published",
        "publication": _record_payload(value.record),
        "as_of": _utc_text(value.as_of),
        "calendar_days": [day.to_payload() for day in value.record.seal.snapshot.days],
    }


def _reference_boundary(reliability: str) -> dict[str, object]:
    """Publish reference capability and unknown upstream clocks explicitly."""

    return {
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "blocked_reason": "exchange_calendar_reference_only",
        "freshness": {
            "source_observed_at": None,
            "source_available_at": None,
            "source_time_status": "not_provided",
        },
        "reliability": reliability,
    }


def _record_payload(value: CalendarFormalPublicationRecord) -> dict[str, object]:
    """Project bounded reference metadata without seal, raw body or Audit objects."""

    value.validate()
    seal = value.seal
    return {
        "publication_id": value.publication_id,
        "publication_hash": seal.publication_hash,
        "activation_id": value.activation_id,
        "dataset_key": seal.dataset.value,
        "exchange": seal.exchange,
        "coverage_start": seal.snapshot.coverage_start.isoformat(),
        "coverage_end": seal.snapshot.coverage_end.isoformat(),
        "contract_version": seal.dataset.contract_version,
        "schema_version": seal.dataset.schema_version,
        "policy_identity": seal.policy_identity,
        "policy_version": seal.policy_version,
        "calendar_response_max_age_seconds": seal.calendar_response_max_age_seconds,
        "published_at": _utc_text(value.published_at),
        "first_seen_at": _utc_text(seal.snapshot_first_seen_at),
        "snapshot_recorded_at": _utc_text(seal.snapshot_recorded_at),
        "source_published_at": _optional_utc_text(seal.snapshot.source_published_at),
        "response_expires_at": _utc_text(value.window.response_expires_at),
    }


def _identity_payload(value: CalendarPublicationPreviewIdentity) -> dict[str, object]:
    """Project all preview identity fields without an unversioned substitute."""

    return {
        "dataset_key": value.dataset_key,
        "contract_version": value.contract_version,
        "schema_version": value.schema_version,
        "policy_identity": value.policy_identity,
        "policy_version": value.policy_version,
        "calendar_response_max_age_seconds": value.calendar_response_max_age_seconds,
    }


def _pointer_payload(value: CalendarPublicationPointerExpectation) -> dict[str, object]:
    """Keep all CAS fields, including explicit nulls for an absent pointer."""

    return {
        "dataset_key": value.dataset_key,
        "publication_key": value.publication_key,
        "pointer_id": value.pointer_id,
        "publication_id": value.publication_id,
        "publication_hash": value.publication_hash,
        "activation_id": value.activation_id,
        "updated_at": _optional_utc_text(value.updated_at),
    }


def _confirmation_payload(value: ConfirmCalendarPublicationIntent) -> dict[str, object]:
    """Return exactly the strict confirmation input, without display-only fields."""

    return {
        "snapshot_reference": value.snapshot_reference.to_payload(),
        "expected_identity": _identity_payload(value.expected_identity),
        "expected_pointer": _pointer_payload(value.expected_pointer),
        "activation_id": value.activation_id,
        "expected_publication_hash": value.expected_publication_hash,
        "preview_hash": value.preview_hash,
    }


def _utc_text(value: datetime) -> str:
    """Encode a validated application instant without relying on a JSON renderer."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_utc_text(value: datetime | None) -> str | None:
    """Preserve unknown upstream times as JSON null."""

    return None if value is None else _utc_text(value)
