"""
Interface Layer - Serializers for Policy Management

定义 DRF 序列化器，用于输入验证和输出格式化。
"""

from rest_framework import serializers
from datetime import date
from typing import Optional

from ..domain.entities import PolicyLevel
from ..infrastructure.models import PolicyLog, RSSSourceConfigModel, PolicyLevelKeywordModel, RSSFetchLog


class PolicyLevelField(serializers.Field):
    """政策档位字段"""

    def to_representation(self, value):
        """序列化"""
        if isinstance(value, PolicyLevel):
            return value.value
        return value

    def to_internal_value(self, data):
        """反序列化"""
        if isinstance(data, PolicyLevel):
            return data

        try:
            return PolicyLevel(data)
        except ValueError:
            raise serializers.ValidationError(
                f"Invalid policy level. Must be one of: "
                f"{[l.value for l in PolicyLevel]}"
            )


class PolicyEventSerializer(serializers.Serializer):
    """政策事件序列化器"""

    event_date = serializers.DateField(required=True)
    level = PolicyLevelField(required=True)
    title = serializers.CharField(max_length=200, required=True)
    description = serializers.CharField(required=True, allow_blank=False)
    evidence_url = serializers.URLField(
        max_length=500,
        required=True,
        allow_blank=False
    )

    def validate_level(self, value):
        """验证档位"""
        if not isinstance(value, PolicyLevel):
            raise serializers.ValidationError("Invalid policy level")
        return value

    def validate_evidence_url(self, value):
        """验证证据 URL"""
        if not value.startswith(("http://", "https://")):
            raise serializers.ValidationError(
                "Evidence URL must start with http:// or https://"
            )
        return value

    def validate(self, attrs):
        """整体验证"""
        level = attrs.get("level")
        description = attrs.get("description", "")

        # P2/P3 需要详细描述
        if level in [PolicyLevel.P2, PolicyLevel.P3]:
            if len(description) < 20:
                raise serializers.ValidationError({
                    "description": f"{level.value} level requires at least 20 characters"
                })

        return attrs


class PolicyLogSerializer(serializers.ModelSerializer):
    """PolicyLog ORM 模型序列化器"""

    level_display = serializers.CharField(source="get_level_display", read_only=True)

    class Meta:
        model = PolicyLog
        fields = [
            'id',
            'event_date',
            'level',
            'level_display',
            'title',
            'description',
            'evidence_url',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class PolicyStatusSerializer(serializers.Serializer):
    """政策状态序列化器"""

    current_level = PolicyLevelField()
    level_name = serializers.CharField()
    is_intervention_active = serializers.BooleanField()
    is_crisis_mode = serializers.BooleanField()
    recommendations = serializers.ListField(child=serializers.CharField())
    as_of_date = serializers.DateField()

    # 响应配置
    market_action = serializers.CharField()
    cash_adjustment = serializers.FloatField()
    signal_pause_hours = serializers.IntegerField(allow_null=True)
    requires_manual_approval = serializers.BooleanField()

    # 最新事件
    latest_event = PolicyEventSerializer(allow_null=True)


class PolicyCreateResponseSerializer(serializers.Serializer):
    """创建政策事件响应序列化器"""

    success = serializers.BooleanField()
    event = PolicyEventSerializer(allow_null=True)
    errors = serializers.ListField(child=serializers.CharField(), required=False)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)
    alert_triggered = serializers.BooleanField()


class PolicyHistorySerializer(serializers.Serializer):
    """政策历史序列化器"""

    events = PolicyEventSerializer(many=True)
    total_count = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class PolicyLevelStatsSerializer(serializers.Serializer):
    """政策档位统计序列化器"""

    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class PolicyStatsSerializer(serializers.Serializer):
    """政策统计序列化器"""

    total = serializers.IntegerField()
    by_level = serializers.DictField(
        child=PolicyLevelStatsSerializer()
    )


class PolicyHistoryWithStatsSerializer(serializers.Serializer):
    """政策历史（含统计）序列化器"""

    events = PolicyEventSerializer(many=True)
    total_count = serializers.IntegerField()
    level_stats = PolicyStatsSerializer()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


# ========== RSS 相关序列化器 ==========

class RSSSourceConfigSerializer(serializers.ModelSerializer):
    """RSS源配置序列化器"""

    category_display = serializers.CharField(source='get_category_display', read_only=True)
    parser_type_display = serializers.CharField(source='get_parser_type_display', read_only=True)
    proxy_type_display = serializers.CharField(source='get_proxy_type_display', read_only=True)

    class Meta:
        model = RSSSourceConfigModel
        fields = '__all__'
        extra_kwargs = {
            'proxy_password': {'write_only': True}  # 密码只写，不返回
        }


class RSSSourceConfigCreateSerializer(serializers.ModelSerializer):
    """RSS源配置创建序列化器"""

    class Meta:
        model = RSSSourceConfigModel
        fields = [
            'name', 'url', 'category', 'is_active',
            'fetch_interval_hours', 'parser_type', 'timeout_seconds',
            'retry_times', 'extract_content',
            'proxy_enabled', 'proxy_host', 'proxy_port',
            'proxy_username', 'proxy_password', 'proxy_type'
        ]


class PolicyLevelKeywordSerializer(serializers.ModelSerializer):
    """政策档位关键词规则序列化器"""

    level_display = serializers.CharField(source='get_level_display', read_only=True)

    class Meta:
        model = PolicyLevelKeywordModel
        fields = '__all__'


class RSSFetchLogSerializer(serializers.ModelSerializer):
    """RSS抓取日志序列化器"""

    source_name = serializers.CharField(source='source.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RSSFetchLog
        fields = '__all__'


class RSSFetchOutputSerializer(serializers.Serializer):
    """RSS抓取输出序列化器"""

    success = serializers.BooleanField()
    sources_processed = serializers.IntegerField()
    total_items = serializers.IntegerField()
    new_policy_events = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())
    details = serializers.ListField(child=serializers.DictField())


class RSSTriggerSerializer(serializers.Serializer):
    """RSS触发抓取序列化器"""

    source_id = serializers.IntegerField(required=False, allow_null=True)
    force_refetch = serializers.BooleanField(required=False, default=False)
