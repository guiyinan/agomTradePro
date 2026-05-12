"""
Interface Layer - Serializers for Policy Management

定义 DRF 序列化器，用于输入验证和输出格式化。

P1-4: 接入输入消毒，防止 XSS 攻击
"""


from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from shared.sanitization import sanitize_plain_text

from ..domain.entities import PolicyLevel

POLICY_LEVEL_CHOICES = [
    ("PX", "PX - 待分类"),
    ("P0", "P0 - 常态"),
    ("P1", "P1 - 预警"),
    ("P2", "P2 - 干预"),
    ("P3", "P3 - 危机"),
]

RSS_SOURCE_CATEGORY_CHOICES = [
    ("gov_docs", "政府文件库"),
    ("central_bank", "央行公告"),
    ("mof", "财政部"),
    ("csrc", "证监会"),
    ("media", "财经媒体"),
    ("other", "其他"),
]

RSS_PARSER_TYPE_CHOICES = [
    ("feedparser", "feedparser"),
    ("httpx", "httpx+manual"),
]

RSS_PROXY_TYPE_CHOICES = [
    ("http", "HTTP"),
    ("https", "HTTPS"),
    ("socks5", "SOCKS5"),
]

RSS_FETCH_STATUS_CHOICES = [
    ("success", "成功"),
    ("error", "失败"),
    ("partial", "部分成功"),
]

RSSHUB_FORMAT_CHOICES = [
    ("", "默认"),
    ("rss", "RSS 2.0"),
    ("atom", "Atom"),
    ("json", "JSON Feed"),
]


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
                f"{[lvl.value for lvl in PolicyLevel]}"
            ) from None


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


class PolicyLogSerializer(serializers.Serializer):
    """Policy log output serializer."""

    id = serializers.IntegerField(read_only=True)
    event_date = serializers.DateField()
    level = serializers.ChoiceField(choices=POLICY_LEVEL_CHOICES)
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    evidence_url = serializers.URLField(max_length=500)
    created_at = serializers.DateTimeField(read_only=True)


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

class RSSSourceConfigSerializer(serializers.Serializer):
    """RSS source config serializer."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    url = serializers.URLField(max_length=500)
    category = serializers.ChoiceField(choices=RSS_SOURCE_CATEGORY_CHOICES)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    is_active = serializers.BooleanField()
    fetch_interval_hours = serializers.IntegerField(min_value=1, max_value=168)
    extract_content = serializers.BooleanField(default=False)
    proxy_enabled = serializers.BooleanField(default=False)
    proxy_host = serializers.CharField(max_length=200, allow_blank=True, required=False)
    proxy_port = serializers.IntegerField(
        min_value=1,
        max_value=65535,
        allow_null=True,
        required=False,
    )
    proxy_username = serializers.CharField(max_length=100, allow_blank=True, required=False)
    proxy_password = serializers.CharField(
        max_length=200,
        allow_blank=True,
        required=False,
        write_only=True,
    )
    proxy_type = serializers.ChoiceField(
        choices=RSS_PROXY_TYPE_CHOICES,
        default="http",
    )
    proxy_type_display = serializers.CharField(
        source="get_proxy_type_display",
        read_only=True,
    )
    parser_type = serializers.ChoiceField(
        choices=RSS_PARSER_TYPE_CHOICES,
        default="feedparser",
    )
    parser_type_display = serializers.CharField(
        source="get_parser_type_display",
        read_only=True,
    )
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=120, default=30)
    retry_times = serializers.IntegerField(min_value=0, max_value=10, default=3)
    rsshub_enabled = serializers.BooleanField(default=False)
    rsshub_route_path = serializers.CharField(max_length=500, allow_blank=True, required=False)
    rsshub_use_global_config = serializers.BooleanField(default=True)
    rsshub_custom_base_url = serializers.URLField(
        max_length=500,
        allow_blank=True,
        required=False,
    )
    rsshub_custom_access_key = serializers.CharField(
        max_length=200,
        allow_blank=True,
        required=False,
    )
    rsshub_format = serializers.ChoiceField(
        choices=RSSHUB_FORMAT_CHOICES,
        allow_blank=True,
        required=False,
        default="",
    )
    last_fetch_at = serializers.DateTimeField(read_only=True)
    last_fetch_status = serializers.CharField(read_only=True)
    last_error_message = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class RSSSourceConfigCreateSerializer(RSSSourceConfigSerializer):
    """RSS source write serializer."""


class PolicyLevelKeywordSerializer(serializers.Serializer):
    """Policy level keyword serializer."""

    id = serializers.IntegerField(read_only=True)
    level = serializers.ChoiceField(choices=POLICY_LEVEL_CHOICES)
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        allow_empty=False,
    )
    weight = serializers.IntegerField()
    category = serializers.CharField(
        max_length=50,
        allow_blank=True,
        allow_null=True,
        required=False,
    )
    is_active = serializers.BooleanField(default=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_keywords(self, value):
        cleaned = [keyword.strip() for keyword in value if keyword.strip()]
        if not cleaned:
            raise serializers.ValidationError("至少填写一个关键词")
        return cleaned


class RSSFetchLogSerializer(serializers.Serializer):
    """RSS fetch log serializer."""

    id = serializers.IntegerField(read_only=True)
    source = serializers.IntegerField(source="source_id", read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    fetched_at = serializers.DateTimeField(read_only=True)
    status = serializers.ChoiceField(choices=RSS_FETCH_STATUS_CHOICES, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    items_count = serializers.IntegerField(read_only=True)
    new_items_count = serializers.IntegerField(read_only=True)
    error_message = serializers.CharField(read_only=True)
    fetch_duration_seconds = serializers.FloatField(read_only=True, allow_null=True)


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
