"""OpenAPI contracts for the opaque calendar workbench endpoints."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers


class CalendarWorkbenchApiErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Stable JSON error envelope for actionable calendar workbench failures."""

    error = serializers.CharField()
    code = serializers.CharField()


class _CalendarWorkbenchFreshnessSerializer(serializers.Serializer[dict[str, object]]):
    """Document source clocks without inventing an upstream observation time."""

    source_observed_at = serializers.DateTimeField(allow_null=True)
    source_available_at = serializers.DateTimeField(allow_null=True)
    source_time_status = serializers.ChoiceField(choices=("not_provided",))


class _CalendarWorkbenchVisibleDataSerializer(serializers.Serializer[dict[str, object]]):
    """Readable calendar workflow fields, without hashes or confirmation echo JSON."""

    publication_status = serializers.ChoiceField(choices=("preview", "published"))
    must_not_execute = serializers.BooleanField()
    must_not_use_for_decision = serializers.BooleanField()
    blocked_reason = serializers.ChoiceField(choices=("exchange_calendar_reference_only",))
    freshness = _CalendarWorkbenchFreshnessSerializer()
    reliability = serializers.ChoiceField(
        choices=("unpublished_publication_preview", "audited_calendar_reference")
    )
    exchange = serializers.CharField()
    coverage_start = serializers.DateField()
    coverage_end = serializers.DateField()
    first_seen_at = serializers.DateTimeField()
    source_published_at = serializers.DateTimeField(allow_null=True)
    message = serializers.CharField()


class CalendarWorkbenchPreviewDataResponseSerializer(_CalendarWorkbenchVisibleDataSerializer):
    """Visible preview fields and original response-age expiry."""

    publication_status = serializers.ChoiceField(choices=("preview",))
    reliability = serializers.ChoiceField(choices=("unpublished_publication_preview",))
    previewed_at = serializers.DateTimeField()
    response_expires_at = serializers.DateTimeField()


class CalendarWorkbenchCommitDataResponseSerializer(_CalendarWorkbenchVisibleDataSerializer):
    """Visible result of publishing without exposing internal identities."""

    publication_status = serializers.ChoiceField(choices=("published",))
    reliability = serializers.ChoiceField(choices=("audited_calendar_reference",))
    transition_label = serializers.CharField()
    published_at = serializers.DateTimeField()
    response_expires_at = serializers.DateTimeField()
    checked_at = serializers.DateTimeField()


@extend_schema_field(
    {
        "type": "string",
        "maxLength": 32768,
        "writeOnly": True,
        "x-tui-hidden": True,
        "description": "Opaque in-memory workbench continuation; never display or copy.",
    }
)
class CalendarWorkbenchOpaqueTokenSchemaField(serializers.CharField):
    """Describe the encrypted continuation as hidden, bounded runtime input."""


class CalendarWorkbenchContinuationInputResponseSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Exact hidden input prepared for the TUI's explicit confirmation action."""

    confirmation_token = CalendarWorkbenchOpaqueTokenSchemaField()


@extend_schema_serializer(
    component_name="CalendarWorkbenchHiddenContinuation",
    extensions={"x-tui-hidden": True},
    description="Runtime-only handoff; do not render, log, copy, or persist in a URL.",
)
class CalendarWorkbenchContinuationResponseSerializer(serializers.Serializer[dict[str, object]]):
    """TUI-only continuation envelope, separate from visible result data."""

    action_key = serializers.ChoiceField(choices=("data-center.calendar-workbench-confirm",))
    input = CalendarWorkbenchContinuationInputResponseSerializer()
    expires_at = serializers.DateTimeField()


class CalendarWorkbenchPrepareSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Success shape with a separate hidden continuation for the TUI runtime."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarWorkbenchPreviewDataResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property
    continuation = CalendarWorkbenchContinuationResponseSerializer()


class CalendarWorkbenchConfirmInputSchemaSerializer(serializers.Serializer[dict[str, object]]):
    """OpenAPI-only request contract for the sole hidden token field."""

    confirmation_token = CalendarWorkbenchOpaqueTokenSchemaField()


class CalendarWorkbenchConfirmSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Success response contains only the safe publication summary."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarWorkbenchCommitDataResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


class CalendarWorkbenchScopeMetadataResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Non-secret active capture metadata selected from the existing catalog."""

    dataset_key = serializers.CharField()
    contract_version = serializers.CharField()
    schema_version = serializers.CharField()
    calendar_response_max_age_seconds = serializers.IntegerField(min_value=1)
    policy_identity = serializers.CharField()
    policy_version = serializers.CharField()
    member_codec_version = serializers.CharField()
    provider_id = serializers.IntegerField(min_value=1)
    provider = serializers.CharField()
    capability = serializers.CharField()
    validator_key = serializers.CharField()


class CalendarWorkbenchScopeDataResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Selected or blocked scope metadata with untouched runtime-status flags."""

    metadata_status = serializers.ChoiceField(choices=("metadata_selected", "blocked"))
    blocked_reason = serializers.CharField(allow_null=True)
    secret_runtime_status = serializers.ChoiceField(choices=("not_checked",))
    current_pointer_status = serializers.ChoiceField(choices=("not_scoped",))
    known_at = serializers.DateTimeField()
    metadata = CalendarWorkbenchScopeMetadataResponseSerializer(allow_null=True)
    message = serializers.CharField()


class CalendarWorkbenchScopeSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Read success envelope; blocked metadata remains an explicit data status."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarWorkbenchScopeDataResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


class _CalendarWorkbenchDaySerializer(serializers.Serializer[dict[str, object]]):
    """One date and its explicit open/closed reference status."""

    exchange = serializers.CharField()
    calendar_date = serializers.DateField()
    is_open = serializers.BooleanField()
    previous_open_date = serializers.DateField(allow_null=True)


class _CalendarWorkbenchCurrentPublicationSerializer(serializers.Serializer[dict[str, object]]):
    """Reference-only current publication details without technical identities."""

    publication_status = serializers.ChoiceField(choices=("published",))
    must_not_execute = serializers.BooleanField()
    must_not_use_for_decision = serializers.BooleanField()
    blocked_reason = serializers.ChoiceField(choices=("exchange_calendar_reference_only",))
    freshness = _CalendarWorkbenchFreshnessSerializer()
    reliability = serializers.ChoiceField(choices=("audited_calendar_reference",))
    exchange = serializers.CharField()
    coverage_start = serializers.DateField()
    coverage_end = serializers.DateField()
    as_of = serializers.DateTimeField()
    first_seen_at = serializers.DateTimeField()
    source_published_at = serializers.DateTimeField(allow_null=True)
    response_expires_at = serializers.DateTimeField()
    calendar_days = serializers.ListField(child=_CalendarWorkbenchDaySerializer())


class CalendarWorkbenchCurrentDataResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Selected configuration and exact current-reference state."""

    configuration_status = serializers.ChoiceField(choices=("metadata_selected", "blocked"))
    current_status = serializers.ChoiceField(choices=("published", "not_found", "blocked"))
    blocked_reason = serializers.CharField(allow_null=True)
    current = _CalendarWorkbenchCurrentPublicationSerializer(allow_null=True)
    message = serializers.CharField()


class CalendarWorkbenchCurrentSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Current read response with configuration and publication status kept explicit."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarWorkbenchCurrentDataResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


__all__ = [
    "CalendarWorkbenchApiErrorResponseSerializer",
    "CalendarWorkbenchConfirmInputSchemaSerializer",
    "CalendarWorkbenchConfirmSuccessResponseSerializer",
    "CalendarWorkbenchCurrentSuccessResponseSerializer",
    "CalendarWorkbenchPrepareSuccessResponseSerializer",
    "CalendarWorkbenchScopeSuccessResponseSerializer",
]
