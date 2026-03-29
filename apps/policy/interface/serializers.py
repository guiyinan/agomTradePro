"""
Interface Layer - Serializers for Policy Management

定义 DRF 序列化器，用于输入验证和输出格式化。

P1-4: 接入输入消毒，防止 XSS 攻击
"""

from datetime import date
from typing import Optional

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from shared.infrastructure.sanitization import sanitize_plain_text

from ..domain.entities import PolicyLevel
from ..infrastructure.models import (
    PolicyLevelKeywordModel,
    PolicyLog,
    RSSFetchLog,
    RSSSourceConfigModel,
)


@extend_schema_field(OpenApiTypes.STR)
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

    def validate_title(self, value):
        """验证标题（含 XSS 消毒）"""
        # P1-4: XSS 消毒
        return sanitize_plain_text(value)

    def validate_description(self, value):
        """验证描述（含 XSS 消毒）"""
        # P1-4: XSS 消毒
        return sanitize_plain_text(value)

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


# ============================================================
# 工作台序列化器
# ============================================================

class WorkbenchSummarySerializer(serializers.Serializer):
    """工作台概览序列化器"""

    policy_level = serializers.SerializerMethodField()
    policy_level_event = serializers.CharField(allow_null=True)
    global_heat_score = serializers.FloatField(allow_null=True)
    global_sentiment_score = serializers.FloatField(allow_null=True)
    global_gate_level = serializers.SerializerMethodField()
    pending_review_count = serializers.IntegerField()
    sla_exceeded_count = serializers.IntegerField()
    effective_today_count = serializers.IntegerField()
    last_fetch_at = serializers.DateTimeField(allow_null=True)

    @extend_schema_field(OpenApiTypes.STR)
    def get_policy_level(self, obj) -> str | None:
        """获取政策档位字符串值"""
        level = getattr(obj, 'policy_level', None)
        if level is None:
            return None
        return level.value if hasattr(level, 'value') else str(level)

    @extend_schema_field(OpenApiTypes.STR)
    def get_global_gate_level(self, obj) -> str | None:
        """获取闸门等级字符串值"""
        level = getattr(obj, 'global_gate_level', None)
        if level is None:
            return None
        return level.value if hasattr(level, 'value') else str(level)


class WorkbenchItemSerializer(serializers.Serializer):
    """工作台事件项序列化器"""

    id = serializers.IntegerField()
    event_date = serializers.DateField()
    event_type = serializers.CharField()
    level = serializers.CharField()
    gate_level = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    description = serializers.CharField()
    evidence_url = serializers.URLField()
    ai_confidence = serializers.FloatField(allow_null=True)
    heat_score = serializers.FloatField(allow_null=True)
    sentiment_score = serializers.FloatField(allow_null=True)
    gate_effective = serializers.BooleanField()
    asset_class = serializers.CharField(allow_null=True)
    asset_scope = serializers.ListField(child=serializers.CharField())
    audit_status = serializers.CharField()
    created_at = serializers.DateTimeField()
    effective_at = serializers.DateTimeField(allow_null=True)
    effective_by_id = serializers.IntegerField(allow_null=True)
    review_notes = serializers.CharField(allow_blank=True)
    rollback_reason = serializers.CharField(allow_blank=True)


class WorkbenchItemsQuerySerializer(serializers.Serializer):
    """工作台事件列表查询序列化器"""

    tab = serializers.ChoiceField(
        choices=['pending', 'effective', 'all'],
        default='all'
    )
    event_type = serializers.ChoiceField(
        choices=['policy', 'hotspot', 'sentiment', 'mixed'],
        required=False,
        allow_null=True
    )
    level = serializers.ChoiceField(
        choices=['P0', 'P1', 'P2', 'P3', 'PX'],
        required=False,
        allow_null=True
    )
    gate_level = serializers.ChoiceField(
        choices=['L0', 'L1', 'L2', 'L3'],
        required=False,
        allow_null=True
    )
    asset_class = serializers.ChoiceField(
        choices=['equity', 'bond', 'commodity', 'fx', 'crypto', 'all'],
        required=False,
        allow_null=True
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    search = serializers.CharField(required=False, allow_blank=True)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)
    offset = serializers.IntegerField(default=0, min_value=0)


class WorkbenchItemsResponseSerializer(serializers.Serializer):
    """工作台事件列表响应序列化器"""

    success = serializers.BooleanField()
    items = WorkbenchItemSerializer(many=True)
    total = serializers.IntegerField()
    error = serializers.CharField(allow_null=True, required=False)


class ApproveEventSerializer(serializers.Serializer):
    """审核通过序列化器"""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RejectEventSerializer(serializers.Serializer):
    """审核拒绝序列化器"""

    reason = serializers.CharField(required=True, allow_blank=False)


class RollbackEventSerializer(serializers.Serializer):
    """回滚生效序列化器"""

    reason = serializers.CharField(required=True, allow_blank=False)


class OverrideEventSerializer(serializers.Serializer):
    """临时豁免序列化器"""

    reason = serializers.CharField(required=True, allow_blank=False)
    new_level = serializers.ChoiceField(
        choices=['P0', 'P1', 'P2', 'P3'],
        required=False,
        allow_null=True
    )


class ActionResponseSerializer(serializers.Serializer):
    """操作响应序列化器"""

    success = serializers.BooleanField()
    event_id = serializers.IntegerField(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


class SentimentGateStateSerializer(serializers.Serializer):
    """热点情绪闸门状态序列化器"""

    success = serializers.BooleanField()
    asset_class = serializers.CharField(allow_null=True)
    gate_level = serializers.CharField(allow_null=True)
    heat_score = serializers.FloatField(allow_null=True)
    sentiment_score = serializers.FloatField(allow_null=True)
    max_position_cap = serializers.FloatField(allow_null=True)
    thresholds = serializers.DictField(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


class IngestionConfigSerializer(serializers.Serializer):
    """摄入配置序列化器"""

    auto_approve_enabled = serializers.BooleanField()
    auto_approve_min_level = serializers.CharField()
    auto_approve_threshold = serializers.FloatField()
    p23_sla_hours = serializers.IntegerField()
    normal_sla_hours = serializers.IntegerField()
    version = serializers.IntegerField(read_only=True)


class SentimentGateConfigSerializer(serializers.Serializer):
    """闸门配置序列化器"""

    asset_class = serializers.CharField()
    heat_l1_threshold = serializers.FloatField()
    heat_l2_threshold = serializers.FloatField()
    heat_l3_threshold = serializers.FloatField()
    sentiment_l1_threshold = serializers.FloatField()
    sentiment_l2_threshold = serializers.FloatField()
    sentiment_l3_threshold = serializers.FloatField()
    max_position_cap_l2 = serializers.FloatField()
    max_position_cap_l3 = serializers.FloatField()
    enabled = serializers.BooleanField()
    version = serializers.IntegerField(read_only=True)


# ============================================================
# 工作台 Bootstrap/Detail/Fetch 序列化器
# ============================================================

class WorkbenchFilterOptionsSerializer(serializers.Serializer):
    """工作台筛选选项序列化器"""

    event_types = serializers.ListField(child=serializers.DictField())
    levels = serializers.ListField(child=serializers.DictField())
    gate_levels = serializers.ListField(child=serializers.DictField())
    asset_classes = serializers.ListField(child=serializers.CharField())
    sources = serializers.ListField(child=serializers.DictField())


class WorkbenchTrendSerializer(serializers.Serializer):
    """工作台趋势数据序列化器"""

    sentiment_recent_30d = serializers.ListField(child=serializers.DictField())
    effective_events_recent_30d = serializers.ListField(child=serializers.DictField())


class WorkbenchFetchStatusSerializer(serializers.Serializer):
    """工作台抓取状态序列化器"""

    last_fetch_at = serializers.DateTimeField(allow_null=True)
    last_fetch_status = serializers.CharField(allow_null=True)
    recent_fetch_errors = serializers.ListField(child=serializers.DictField())


class WorkbenchBootstrapSerializer(serializers.Serializer):
    """工作台启动数据序列化器"""

    summary = WorkbenchSummarySerializer()
    default_list = WorkbenchItemSerializer(many=True)
    filter_options = WorkbenchFilterOptionsSerializer()
    trend = WorkbenchTrendSerializer()
    fetch_status = WorkbenchFetchStatusSerializer()


class WorkbenchItemDetailSerializer(serializers.Serializer):
    """工作台事件详情序列化器"""

    # 基础字段
    id = serializers.IntegerField()
    event_date = serializers.DateField()
    event_type = serializers.CharField()
    level = serializers.CharField()
    gate_level = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    description = serializers.CharField()
    evidence_url = serializers.URLField()

    # AI 分析字段
    ai_confidence = serializers.FloatField(allow_null=True)
    heat_score = serializers.FloatField(allow_null=True)
    sentiment_score = serializers.FloatField(allow_null=True)
    structured_data = serializers.DictField(allow_null=True)

    # 闸门与生效
    gate_effective = serializers.BooleanField()
    effective_at = serializers.DateTimeField(allow_null=True)
    effective_by_id = serializers.IntegerField(allow_null=True)
    effective_by_name = serializers.CharField(allow_null=True)

    # 审核字段
    audit_status = serializers.CharField()
    reviewed_by_id = serializers.IntegerField(allow_null=True)
    reviewed_by_name = serializers.CharField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    review_notes = serializers.CharField(allow_blank=True)

    # 资产范围
    asset_class = serializers.CharField(allow_null=True)
    asset_scope = serializers.ListField(child=serializers.CharField())

    # 回滚信息
    rollback_reason = serializers.CharField(allow_blank=True)

    # 来源信息
    rss_source_id = serializers.IntegerField(allow_null=True)
    rss_source_name = serializers.CharField(allow_null=True)
    rss_item_guid = serializers.CharField(allow_null=True)

    # 时间戳
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField(allow_null=True)


class WorkbenchFetchInputSerializer(serializers.Serializer):
    """工作台抓取输入序列化器"""

    source_id = serializers.IntegerField(required=False, allow_null=True)
    force_refetch = serializers.BooleanField(required=False, default=False)


class WorkbenchFetchOutputSerializer(serializers.Serializer):
    """工作台抓取输出序列化器"""

    success = serializers.BooleanField()
    mode = serializers.CharField()  # 'all' or 'single'
    task_id = serializers.CharField(allow_null=True)
    sources_processed = serializers.IntegerField()
    total_items = serializers.IntegerField()
    new_policy_events = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField())
    details = serializers.ListField(child=serializers.DictField())
