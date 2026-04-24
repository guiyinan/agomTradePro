"""DRF serializers for the signal API."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from shared.sanitization import sanitize_plain_text


class InvestmentSignalSerializer(serializers.Serializer):
    """Read serializer for investment signal payloads."""

    id = serializers.IntegerField(read_only=True)
    asset_code = serializers.CharField(read_only=True)
    asset_class = serializers.CharField(read_only=True)
    direction = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    logic_desc = serializers.CharField(read_only=True)
    invalidation_description = serializers.CharField(read_only=True, allow_blank=True)
    invalidation_rule = serializers.JSONField(read_only=True)
    human_readable_invalidation = serializers.SerializerMethodField()
    target_regime = serializers.CharField(read_only=True)
    rejection_reason = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    invalidated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    backtest_performance_score = serializers.FloatField(read_only=True, allow_null=True)
    avg_backtest_return = serializers.FloatField(read_only=True, allow_null=True)

    @extend_schema_field(OpenApiTypes.STR)
    def get_human_readable_invalidation(self, obj) -> str:
        """Return the human-readable invalidation description."""

        if isinstance(obj, dict):
            return (
                obj.get("human_readable_invalidation")
                or obj.get("invalidation_description")
                or ""
            )
        if hasattr(obj, "get_human_readable_rules"):
            return obj.get_human_readable_rules()
        return getattr(obj, "invalidation_description", "") or ""


class InvestmentSignalCreateSerializer(serializers.Serializer):
    """Write serializer for creating investment signals."""

    asset_code = serializers.CharField()
    asset_class = serializers.CharField()
    direction = serializers.CharField()
    logic_desc = serializers.CharField()
    invalidation_logic = serializers.CharField(
        write_only=True,
        required=True,
        help_text="自然语言描述的证伪逻辑，如 'PMI 跌破 50' 或 'CPI > 3 且 M2 < 10'",
    )
    target_regime = serializers.CharField()

    def validate_invalidation_logic(self, value):
        """Validate and sanitize invalidation logic."""

        value = sanitize_plain_text(value)
        if not value or len(value.strip()) < 5:
            raise serializers.ValidationError("证伪逻辑至少需要 5 个字符")

        quantifiable_keywords = [
            "跌破", "突破", "小于", "大于", "低于", "高于",
            "<", ">", "<=", ">=", "涨幅", "跌幅", "%",
        ]
        has_keyword = any(kw in value for kw in quantifiable_keywords)
        if not has_keyword:
            raise serializers.ValidationError(
                "证伪逻辑需要包含可量化条件，如：跌破、突破、<、>、涨幅、跌幅等"
            )

        return value

    def validate_logic_desc(self, value):
        """Validate and sanitize logic description."""

        return sanitize_plain_text(value)

    def create(self, validated_data):
        """Create a signal via application query services."""

        from apps.signal.application.query_services import create_investment_signal_payload

        try:
            return create_investment_signal_payload(**validated_data)
        except ValueError as exc:
            raise serializers.ValidationError(
                {"invalidation_logic": str(exc)}
            ) from exc


class InvestmentSignalUpdateSerializer(serializers.Serializer):
    """Write serializer for updating investment signals."""

    asset_code = serializers.CharField(required=False)
    asset_class = serializers.CharField(required=False)
    direction = serializers.CharField(required=False)
    logic_desc = serializers.CharField(required=False)
    invalidation_logic = serializers.CharField(required=False)
    target_regime = serializers.CharField(required=False)

    def validate_invalidation_logic(self, value):
        """Reuse create-time invalidation validation."""

        return InvestmentSignalCreateSerializer().validate_invalidation_logic(value)

    def validate_logic_desc(self, value):
        """Reuse create-time logic sanitization."""

        return sanitize_plain_text(value)


class InvestmentSignalValidateRequestSerializer(serializers.Serializer):
    """Serializer for signal validation request"""

    signal_id = serializers.IntegerField(required=False)
    asset_code = serializers.CharField(required=False)
    logic_desc = serializers.CharField(required=False)
    invalidation_logic = serializers.CharField(required=False)
    invalidation_threshold = serializers.FloatField(required=False)


class InvestmentSignalValidateResponseSerializer(serializers.Serializer):
    """Serializer for signal validation response"""

    success = serializers.BooleanField()
    is_eligible = serializers.BooleanField()
    eligibility = serializers.CharField(allow_null=True)
    rejection_reason = serializers.CharField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), allow_empty=True)


class SignalListQuerySerializer(serializers.Serializer):
    """Serializer for signal list query parameters"""

    status = serializers.CharField(required=False, allow_null=True)
    asset_class = serializers.CharField(required=False, allow_null=True)
    direction = serializers.CharField(required=False, allow_null=True)
    search = serializers.CharField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=500)


class UnifiedSignalSerializer(serializers.Serializer):
    """Read serializer for unified signal payloads."""

    id = serializers.IntegerField(read_only=True)
    signal_date = serializers.CharField(read_only=True)
    signal_source = serializers.CharField(read_only=True)
    signal_source_display = serializers.CharField(read_only=True, required=False)
    signal_type = serializers.CharField(read_only=True)
    signal_type_display = serializers.CharField(read_only=True, required=False)
    asset_code = serializers.CharField(read_only=True)
    asset_name = serializers.CharField(read_only=True, allow_blank=True)
    target_weight = serializers.FloatField(read_only=True, allow_null=True)
    current_weight = serializers.FloatField(read_only=True, allow_null=True)
    priority = serializers.IntegerField(read_only=True)
    priority_display = serializers.CharField(read_only=True, required=False)
    is_executed = serializers.BooleanField(read_only=True)
    executed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reason = serializers.CharField(read_only=True)
    action_required = serializers.CharField(read_only=True, allow_blank=True)
    extra_data = serializers.JSONField(read_only=True)
    related_signal_id = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
