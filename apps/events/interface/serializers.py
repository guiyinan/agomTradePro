"""
Events Interface Serializers

事件 DRF 序列化器定义。
"""

import json
from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers

from apps.events.domain.entities import EventType

# ========== 请求序列化器 ==========


JsonObject = dict[str, Any]

MAX_EVENT_PAYLOAD_BYTES = 256 * 1024
MAX_EVENT_METADATA_BYTES = 64 * 1024


def _validate_json_object(
    value: JsonObject,
    *,
    field_name: str,
    max_bytes: int,
) -> JsonObject:
    """Ensure an event object is finite, JSON serializable, and size bounded."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError(f"{field_name} must contain valid JSON values.") from exc
    if len(encoded) > max_bytes:
        raise serializers.ValidationError(f"{field_name} exceeds the {max_bytes}-byte limit.")
    return value


class StrictFieldsSerializer(serializers.Serializer[JsonObject]):
    """Reject request fields that are not part of the published contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return cast(JsonObject, super().to_internal_value(data))


class EventPublishRequestSerializer(StrictFieldsSerializer):
    """发布事件请求序列化器"""

    event_type = serializers.ChoiceField(
        choices=[e.value for e in EventType if e is not EventType.UNKNOWN]
    )
    payload = serializers.DictField()
    metadata = serializers.DictField(required=False)
    event_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    correlation_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )
    causation_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )

    def validate_payload(self, value: JsonObject) -> JsonObject:
        """Reject non-JSON and oversized event payloads."""

        return _validate_json_object(
            value,
            field_name="payload",
            max_bytes=MAX_EVENT_PAYLOAD_BYTES,
        )

    def validate_metadata(self, value: JsonObject) -> JsonObject:
        """Reject non-JSON and oversized event metadata."""

        return _validate_json_object(
            value,
            field_name="metadata",
            max_bytes=MAX_EVENT_METADATA_BYTES,
        )


class EventSubscriptionRequestSerializer(StrictFieldsSerializer):
    """事件订阅请求序列化器"""

    event_type = serializers.ChoiceField(choices=[e.value for e in EventType])
    handler_class = serializers.CharField()
    filter_criteria = serializers.DictField(required=False)
    priority = serializers.IntegerField(required=False, default=100)


class EventQueryRequestSerializer(StrictFieldsSerializer):
    """事件查询请求序列化器"""

    event_type = serializers.ChoiceField(
        choices=[e.value for e in EventType], required=False, allow_null=True
    )
    event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=[e.value for e in EventType]),
        required=False,
        allow_null=True,
    )
    correlation_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=64,
    )
    since = serializers.DateTimeField(required=False, allow_null=True)
    until = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)

    def validate(self, attrs: JsonObject) -> JsonObject:
        """Reject ambiguous filters and inverted time windows."""

        event_type = attrs.get("event_type")
        event_types = attrs.get("event_types")
        if event_type is not None and event_types is not None:
            raise serializers.ValidationError("Use either event_type or event_types, not both.")
        if event_types is not None:
            if not event_types:
                raise serializers.ValidationError({"event_types": ["This list may not be empty."]})
            if len(event_types) != len(set(event_types)):
                raise serializers.ValidationError(
                    {"event_types": ["Duplicate event types are not allowed."]}
                )

        since = attrs.get("since")
        until = attrs.get("until")
        if since is not None and until is not None and since > until:
            raise serializers.ValidationError(
                {"until": ["Must be greater than or equal to since."]}
            )
        return attrs


class _StrictReplaySerializer(StrictFieldsSerializer):
    """Reject undeclared replay fields, including arbitrary handler identities."""

    def validate(self, attrs: JsonObject) -> JsonObject:
        """Reject replay windows whose end precedes their start."""

        start_at = attrs.get("start_at")
        end_at = attrs.get("end_at")
        if start_at is not None and end_at is not None and start_at > end_at:
            raise serializers.ValidationError(
                {"end_at": ["Must be greater than or equal to start_at."]}
            )
        return attrs


class EventReplayPreviewRequestSerializer(_StrictReplaySerializer):
    """Strict preview request for one registered replay target."""

    target_key = serializers.CharField(max_length=128)
    event_type = serializers.ChoiceField(
        choices=[e.value for e in EventType if e is not EventType.UNKNOWN],
        required=True,
    )
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=1000,
    )


class EventReplayCommitRequestSerializer(EventReplayPreviewRequestSerializer):
    """Strict commit request with an explicit idempotency key."""

    idempotency_key = serializers.CharField(max_length=128)


EventReplayRequestSerializer = EventReplayPreviewRequestSerializer


# ========== 响应序列化器 ==========


class EventSerializer(serializers.Serializer[JsonObject]):
    """事件序列化器"""

    event_id = serializers.CharField()
    event_type = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    payload = serializers.DictField()
    metadata = serializers.DictField()
    correlation_id = serializers.CharField(allow_null=True, required=False)
    causation_id = serializers.CharField(allow_null=True, required=False)
    version = serializers.IntegerField()


class EventPublishResponseSerializer(serializers.Serializer[JsonObject]):
    """发布事件响应序列化器"""

    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    event_id = serializers.CharField()
    published_at = serializers.DateTimeField()
    subscribers_notified = serializers.IntegerField(required=False, default=0)


class EventQueryResponseSerializer(serializers.Serializer[JsonObject]):
    """事件查询响应序列化器"""

    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    events = EventSerializer(many=True)
    total_count = serializers.IntegerField()
    queried_at = serializers.DateTimeField()
    has_more = serializers.BooleanField(required=False, default=False)


class EventMetricsSerializer(serializers.Serializer[JsonObject]):
    """事件指标序列化器"""

    total_published = serializers.IntegerField()
    total_processed = serializers.IntegerField()
    total_failed = serializers.IntegerField()
    total_subscribers = serializers.IntegerField()
    avg_processing_time_ms = serializers.FloatField()
    last_event_at = serializers.DateTimeField(allow_null=True, required=False)
    success_rate = serializers.FloatField()


class EventStatisticsResponseSerializer(serializers.Serializer[JsonObject]):
    """事件统计响应序列化器"""

    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    metrics = EventMetricsSerializer()
    events_by_type = serializers.DictField()
    active_subscriptions = serializers.IntegerField()
    queue_size = serializers.IntegerField()


class EventBusStatusSerializer(serializers.Serializer[JsonObject]):
    """事件总线状态序列化器"""

    is_running = serializers.BooleanField()
    total_subscribers = serializers.IntegerField()
    queue_size = serializers.IntegerField()
    last_event_at = serializers.DateTimeField(allow_null=True, required=False)
    uptime_seconds = serializers.FloatField()


class BaseResponseSerializer(serializers.Serializer[JsonObject]):
    """基础响应序列化器"""

    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()


class EventReplayResponseSerializer(BaseResponseSerializer):
    """事件重放响应序列化器"""

    events_replayed = serializers.IntegerField()
    replayed_at = serializers.DateTimeField()
    duration_ms = serializers.IntegerField(required=False, default=0)
