"""
Events Interface Serializers

事件 DRF 序列化器定义。
"""

from datetime import datetime

from rest_framework import serializers

from apps.events.application.dtos import (
    EventBusStatusDTO,
    EventDTO,
    EventMetricsDTO,
    EventPublishRequestDTO,
    EventPublishResponseDTO,
    EventQueryRequestDTO,
    EventQueryResponseDTO,
    EventReplayRequestDTO,
    EventSubscriptionRequestDTO,
)
from apps.events.domain.entities import EventType

# ========== 请求序列化器 ==========


class EventPublishRequestSerializer(serializers.Serializer):
    """发布事件请求序列化器"""
    event_type = serializers.ChoiceField(choices=[e.value for e in EventType])
    payload = serializers.DictField()
    metadata = serializers.DictField(required=False)
    event_id = serializers.CharField(required=False, allow_null=True)
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    correlation_id = serializers.CharField(required=False, allow_null=True)
    causation_id = serializers.CharField(required=False, allow_null=True)


class EventSubscriptionRequestSerializer(serializers.Serializer):
    """事件订阅请求序列化器"""
    event_type = serializers.ChoiceField(choices=[e.value for e in EventType])
    handler_class = serializers.CharField()
    filter_criteria = serializers.DictField(required=False)
    priority = serializers.IntegerField(required=False, default=100)


class EventQueryRequestSerializer(serializers.Serializer):
    """事件查询请求序列化器"""
    event_type = serializers.ChoiceField(
        choices=[e.value for e in EventType],
        required=False,
        allow_null=True
    )
    event_types = serializers.ListField(
        child=serializers.ChoiceField(choices=[e.value for e in EventType]),
        required=False,
        allow_null=True
    )
    correlation_id = serializers.CharField(required=False, allow_null=True)
    since = serializers.DateTimeField(required=False, allow_null=True)
    until = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=1000)


class EventReplayRequestSerializer(serializers.Serializer):
    """事件重放请求序列化器"""
    event_type = serializers.ChoiceField(
        choices=[e.value for e in EventType],
        required=False,
        allow_null=True
    )
    since = serializers.DateTimeField(required=False, allow_null=True)
    until = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=1000, min_value=1, max_value=10000)
    target_handler_class = serializers.CharField(required=False, allow_null=True)


# ========== 响应序列化器 ==========


class EventSerializer(serializers.Serializer):
    """事件序列化器"""
    event_id = serializers.CharField()
    event_type = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    payload = serializers.DictField()
    metadata = serializers.DictField()
    correlation_id = serializers.CharField(allow_null=True, required=False)
    causation_id = serializers.CharField(allow_null=True, required=False)
    version = serializers.IntegerField()


class EventPublishResponseSerializer(serializers.Serializer):
    """发布事件响应序列化器"""
    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    event_id = serializers.CharField()
    published_at = serializers.DateTimeField()
    subscribers_notified = serializers.IntegerField(required=False, default=0)


class EventQueryResponseSerializer(serializers.Serializer):
    """事件查询响应序列化器"""
    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    events = EventSerializer(many=True)
    total_count = serializers.IntegerField()
    queried_at = serializers.DateTimeField()
    has_more = serializers.BooleanField(required=False, default=False)


class EventMetricsSerializer(serializers.Serializer):
    """事件指标序列化器"""
    total_published = serializers.IntegerField()
    total_processed = serializers.IntegerField()
    total_failed = serializers.IntegerField()
    total_subscribers = serializers.IntegerField()
    avg_processing_time_ms = serializers.FloatField()
    last_event_at = serializers.DateTimeField(allow_null=True, required=False)
    success_rate = serializers.FloatField()


class EventStatisticsResponseSerializer(serializers.Serializer):
    """事件统计响应序列化器"""
    success = serializers.BooleanField()
    message = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    metrics = EventMetricsSerializer()
    events_by_type = serializers.DictField()
    active_subscriptions = serializers.IntegerField()
    queue_size = serializers.IntegerField()


class EventBusStatusSerializer(serializers.Serializer):
    """事件总线状态序列化器"""
    is_running = serializers.BooleanField()
    total_subscribers = serializers.IntegerField()
    queue_size = serializers.IntegerField()
    last_event_at = serializers.DateTimeField(allow_null=True, required=False)
    uptime_seconds = serializers.FloatField()


class BaseResponseSerializer(serializers.Serializer):
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
