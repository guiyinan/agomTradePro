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

    class Meta:
        model = InvestmentSignalModel
        fields = [
            'id', 'asset_code', 'asset_class', 'direction', 'status',
            'logic_desc', 'invalidation_logic', 'invalidation_threshold',
            'target_regime', 'rejection_reason', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'rejection_reason']


class InvestmentSignalCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating InvestmentSignal"""

    class Meta:
        model = InvestmentSignalModel
        fields = [
            'asset_code', 'asset_class', 'direction',
            'logic_desc', 'invalidation_logic', 'invalidation_threshold',
            'target_regime'
        ]

    def validate_invalidation_logic(self, value):
        """验证证伪逻辑"""
        if not value or len(value.strip()) < 10:
            raise serializers.ValidationError(
                "证伪逻辑至少需要 10 个字符"
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
