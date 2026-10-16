"""OpenAPI shapes for the reference-only calendar publication endpoints."""

from __future__ import annotations

from rest_framework import serializers

from apps.data_center.interface.calendar_publication_serializers import (
    ConfirmCalendarPublicationInputSerializer,
    PreviewCalendarPublicationInputSerializer,
)


class CalendarApiErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Stable error envelope emitted by the shared Agom exception handler."""

    error = serializers.CharField()
    code = serializers.CharField()
    details = serializers.JSONField(required=False)


class CalendarFreshnessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Preserve unknown upstream source clocks as null in each response."""

    source_observed_at = serializers.DateTimeField(allow_null=True)
    source_available_at = serializers.DateTimeField(allow_null=True)
    source_time_status = serializers.CharField()


class CalendarReferenceResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Capability boundary shared by every calendar reference response."""

    must_not_execute = serializers.BooleanField()
    must_not_use_for_decision = serializers.BooleanField()
    blocked_reason = serializers.CharField()
    freshness = CalendarFreshnessResponseSerializer()
    reliability = serializers.CharField()
    publication_status = serializers.CharField()


class CalendarSnapshotReferenceResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Exact source and RawPayload identity returned by the capture stage."""

    snapshot_id = serializers.UUIDField()
    exchange = serializers.CharField()
    coverage_start = serializers.DateField()
    coverage_end = serializers.DateField()
    content_hash = serializers.CharField()
    record_digest = serializers.CharField()
    raw_payload_id = serializers.UUIDField()
    raw_payload_hash = serializers.CharField()
    raw_record_digest = serializers.CharField()


class CalendarPreviewIntentResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Next-step request accepted by the strict preview input serializer."""

    snapshot_reference = CalendarSnapshotReferenceResponseSerializer()


class CalendarCaptureResponseSerializer(CalendarReferenceResponseSerializer):
    """Safe capture receipt with the next preview input ready to echo."""

    snapshot_reference = CalendarSnapshotReferenceResponseSerializer()
    first_seen_at = serializers.DateTimeField()
    recorded_at = serializers.DateTimeField()
    source_published_at = serializers.DateTimeField(allow_null=True)
    preview_intent = CalendarPreviewIntentResponseSerializer()


class CalendarPublicationIdentityResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Exact catalog and response-age identity echoed at confirmation."""

    dataset_key = serializers.CharField()
    contract_version = serializers.CharField()
    schema_version = serializers.CharField()
    policy_identity = serializers.CharField()
    policy_version = serializers.CharField()
    calendar_response_max_age_seconds = serializers.IntegerField(min_value=1)


class CalendarPointerExpectationResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Complete pointer CAS echo, with nulls for the no-current-pointer case."""

    dataset_key = serializers.CharField()
    publication_key = serializers.CharField()
    pointer_id = serializers.UUIDField(allow_null=True)
    publication_id = serializers.UUIDField(allow_null=True)
    publication_hash = serializers.CharField(allow_null=True)
    activation_id = serializers.CharField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class CalendarConfirmationIntentResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Machine-echoable body accepted by the strict confirm input serializer."""

    snapshot_reference = CalendarSnapshotReferenceResponseSerializer()
    expected_identity = CalendarPublicationIdentityResponseSerializer()
    expected_pointer = CalendarPointerExpectationResponseSerializer()
    activation_id = serializers.CharField()
    expected_publication_hash = serializers.CharField()
    preview_hash = serializers.CharField()


class CalendarPreviewResponseSerializer(CalendarReferenceResponseSerializer):
    """Complete preview display and exact confirmation echo."""

    snapshot_reference = CalendarSnapshotReferenceResponseSerializer()
    identity = CalendarPublicationIdentityResponseSerializer()
    first_seen_at = serializers.DateTimeField()
    snapshot_recorded_at = serializers.DateTimeField()
    source_published_at = serializers.DateTimeField(allow_null=True)
    response_expires_at = serializers.DateTimeField()
    previewed_at = serializers.DateTimeField()
    confirmation_intent = CalendarConfirmationIntentResponseSerializer()


class CalendarPublicationRecordResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Public publication metadata without seals, raw bodies, or Audit objects."""

    publication_id = serializers.UUIDField()
    publication_hash = serializers.CharField()
    activation_id = serializers.CharField()
    dataset_key = serializers.CharField()
    exchange = serializers.CharField()
    coverage_start = serializers.DateField()
    coverage_end = serializers.DateField()
    contract_version = serializers.CharField()
    schema_version = serializers.CharField()
    policy_identity = serializers.CharField()
    policy_version = serializers.CharField()
    calendar_response_max_age_seconds = serializers.IntegerField(min_value=1)
    published_at = serializers.DateTimeField()
    first_seen_at = serializers.DateTimeField()
    snapshot_recorded_at = serializers.DateTimeField()
    source_published_at = serializers.DateTimeField(allow_null=True)
    response_expires_at = serializers.DateTimeField()


class CalendarPublicationCommitResponseSerializer(CalendarReferenceResponseSerializer):
    """Commit receipt with transition and bounded publication metadata."""

    transition = serializers.ChoiceField(
        choices=("first_publish", "forward_publish", "exact_current_replay")
    )
    publication = CalendarPublicationRecordResponseSerializer()
    checked_at = serializers.DateTimeField()


class CalendarDayResponseSerializer(serializers.Serializer[dict[str, object]]):
    """One explicit open or closed exchange date from the source snapshot."""

    exchange = serializers.CharField()
    calendar_date = serializers.DateField()
    is_open = serializers.BooleanField()
    previous_open_date = serializers.DateField()


class CalendarCurrentResponseSerializer(CalendarReferenceResponseSerializer):
    """Exact current publication, reference days, and server knowledge cutoff."""

    publication = CalendarPublicationRecordResponseSerializer()
    as_of = serializers.DateTimeField()
    calendar_days = serializers.ListField(child=CalendarDayResponseSerializer())


class CalendarCaptureSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Common success envelope for the capture response."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarCaptureResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


class CalendarPreviewSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Common success envelope for the preview response."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarPreviewResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


class CalendarCommitSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Common success envelope for publish and exact replay responses."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarPublicationCommitResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


class CalendarCurrentSuccessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Common success envelope for the exact current-read response."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    data = CalendarCurrentResponseSerializer()  # type: ignore[assignment]  # shadows DRF .data property


__all__ = [
    "CalendarApiErrorResponseSerializer",
    "CalendarCaptureSuccessResponseSerializer",
    "CalendarCaptureResponseSerializer",
    "CalendarCommitSuccessResponseSerializer",
    "CalendarCurrentSuccessResponseSerializer",
    "CalendarCurrentResponseSerializer",
    "CalendarPreviewSuccessResponseSerializer",
    "CalendarPreviewResponseSerializer",
    "CalendarPublicationCommitResponseSerializer",
    "ConfirmCalendarPublicationInputSerializer",
    "PreviewCalendarPublicationInputSerializer",
]
