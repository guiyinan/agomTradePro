"""
DRF Serializers for Signal API.
"""

from rest_framework import serializers
from datetime import date
from typing import Dict, Any, Optional

from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.domain.entities import SignalStatus


class InvestmentSignalSerializer(serializers.ModelSerializer):
    """Serializer for InvestmentSignalModel"""

    # 添加结构化证伪规则字段（只读）
    invalidation_rule = serializers.JSONField(source='invalidation_rule_json', read_only=True)
    human_readable_invalidation = serializers.SerializerMethodField()

    class Meta:
        model = InvestmentSignalModel
        fields = [
            'id', 'asset_code', 'asset_class', 'direction', 'status',
            'logic_desc', 'invalidation_description', 'invalidation_rule',
            'human_readable_invalidation', 'target_regime', 'rejection_reason',
            'created_at', 'updated_at', 'invalidated_at',
            'backtest_performance_score', 'avg_backtest_return',
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'rejection_reason',
            'invalidated_at', 'backtest_performance_score', 'avg_backtest_return'
        ]

    def get_human_readable_invalidation(self, obj):
        """获取人类可读的证伪描述"""
        return obj.get_human_readable_rules()


class InvestmentSignalCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating InvestmentSignal"""

    # 新的证伪字段
    invalidation_logic = serializers.CharField(
        write_only=True,
        required=True,
        help_text="自然语言描述的证伪逻辑，如 'PMI 跌破 50' 或 'CPI > 3 且 M2 < 10'"
    )

    class Meta:
        model = InvestmentSignalModel
        fields = [
            'asset_code', 'asset_class', 'direction',
            'logic_desc', 'invalidation_logic', 'target_regime'
        ]

    def validate_invalidation_logic(self, value):
        """验证证伪逻辑"""
        if not value or len(value.strip()) < 5:
            raise serializers.ValidationError(
                "证伪逻辑至少需要 5 个字符"
            )

        # 检查是否包含可量化关键词
        quantifiable_keywords = [
            '跌破', '突破', '小于', '大于', '低于', '高于',
            '<', '>', '<=', '>=', '涨幅', '跌幅', '%'
        ]
        has_keyword = any(kw in value for kw in quantifiable_keywords)
        if not has_keyword:
            raise serializers.ValidationError(
                "证伪逻辑需要包含可量化条件，如：跌破、突破、<、>、涨幅、跌幅等"
            )

        return value

    def create(self, validated_data):
        """创建信号，解析证伪逻辑"""
        from apps.signal.domain.parser import InvalidationLogicParser

        invalidation_logic = validated_data.pop('invalidation_logic')

        # 解析证伪逻辑
        parser = InvalidationLogicParser()
        parse_result = parser.parse(invalidation_logic)

        if not parse_result.success:
            raise serializers.ValidationError({
                'invalidation_logic': f"解析失败: {parse_result.error}"
            })

        # 创建信号
        signal = InvestmentSignalModel.objects.create(
            **validated_data,
            invalidation_description=invalidation_logic,
            invalidation_rule_json=parse_result.rule.to_dict(),
        )

        return signal


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


class UnifiedSignalSerializer(serializers.ModelSerializer):
    """Serializer for UnifiedSignalModel"""

    signal_source_display = serializers.CharField(source='get_signal_source_display', read_only=True)
    signal_type_display = serializers.CharField(source='get_signal_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        from apps.signal.infrastructure.models import UnifiedSignalModel
        model = UnifiedSignalModel
        fields = [
            'id',
            'signal_date',
            'signal_source',
            'signal_source_display',
            'signal_type',
            'signal_type_display',
            'asset_code',
            'asset_name',
            'target_weight',
            'current_weight',
            'priority',
            'priority_display',
            'is_executed',
            'executed_at',
            'reason',
            'action_required',
            'extra_data',
            'related_signal_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'executed_at']
