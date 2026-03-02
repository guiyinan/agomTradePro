"""
Alpha Trigger DRF Serializers

Alpha 事件触发的 API 序列化器。

负责输入验证和输出格式化。
"""

from rest_framework import serializers
from typing import Any, Dict, List, Optional

from ..domain.entities import (
    AlphaTrigger,
    AlphaCandidate,
    TriggerType,
    TriggerStatus,
    SignalStrength,
    InvalidationCondition,
    InvalidationType,
    CandidateStatus,
)


# ========== Enum Serializers ==========


class TriggerTypeSerializer(serializers.Field):
    """触发器类型序列化器"""

    def to_representation(self, obj: TriggerType) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> TriggerType:
        try:
            return TriggerType(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid trigger type: {data}")


class TriggerStatusSerializer(serializers.Field):
    """触发器状态序列化器"""

    def to_representation(self, obj: TriggerStatus) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> TriggerStatus:
        try:
            return TriggerStatus(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid trigger status: {data}")


class SignalStrengthSerializer(serializers.Field):
    """信号强度序列化器"""

    def to_representation(self, obj: SignalStrength) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> SignalStrength:
        try:
            return SignalStrength(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid signal strength: {data}")


class CandidateStatusSerializer(serializers.Field):
    """候选状态序列化器"""

    def to_representation(self, obj: CandidateStatus) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> CandidateStatus:
        try:
            return CandidateStatus(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid candidate status: {data}")


class InvalidationTypeSerializer(serializers.Field):
    """证伪类型序列化器"""

    def to_representation(self, obj: InvalidationType) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> InvalidationType:
        try:
            return InvalidationType(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid invalidation type: {data}")


# ========== Nested Serializers ==========


class InvalidationConditionSerializer(serializers.Serializer):
    """证伪条件序列化器"""

    condition_type = InvalidationTypeSerializer(
        help_text="证伪类型"
    )

    indicator_code = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="指标代码"
    )

    threshold = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="阈值"
    )

    direction = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="方向 (above/below)"
    )

    time_limit_hours = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="时间限制（小时）"
    )

    custom_condition = serializers.DictField(
        default=dict,
        required=False,
        help_text="自定义条件"
    )

    def to_domain(self) -> InvalidationCondition:
        """转换为 Domain 层实体"""
        return InvalidationCondition(
            condition_type=InvalidationType(self.validated_data["condition_type"]),
            indicator_code=self.validated_data.get("indicator_code"),
            threshold=self.validated_data.get("threshold"),
            direction=self.validated_data.get("direction"),
            time_limit_hours=self.validated_data.get("time_limit_hours"),
            custom_condition=self.validated_data.get("custom_condition", {}),
        )


# ========== Main Serializers ==========


class AlphaTriggerSerializer(serializers.Serializer):
    """
    Alpha 触发器序列化器

    用于触发器的创建和查询。
    """

    trigger_id = serializers.CharField(
        read_only=True,
        help_text="触发器 ID"
    )

    trigger_type = TriggerTypeSerializer(
        help_text="触发器类型"
    )

    asset_code = serializers.CharField(
        help_text="资产代码"
    )

    asset_class = serializers.CharField(
        help_text="资产类别"
    )

    direction = serializers.ChoiceField(
        choices=["LONG", "SHORT", "NEUTRAL"],
        help_text="方向"
    )

    trigger_condition = serializers.DictField(
        default=dict,
        help_text="触发条件"
    )

    invalidation_conditions = InvalidationConditionSerializer(
        many=True,
        default=list,
        help_text="证伪条件列表"
    )

    strength = SignalStrengthSerializer(
        read_only=True,
        help_text="信号强度"
    )

    confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="置信度"
    )

    status = TriggerStatusSerializer(
        read_only=True,
        help_text="状态"
    )

    thesis = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="投资论点"
    )

    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="创建时间"
    )

    triggered_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="触发时间"
    )

    invalidated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="证伪时间"
    )

    expires_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="过期时间"
    )

    source_signal_id = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="源信号 ID"
    )

    related_regime = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="相关 Regime"
    )

    related_policy_level = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="相关 Policy 档位"
    )

    custom_data = serializers.DictField(
        default=dict,
        required=False,
        help_text="自定义数据"
    )

    def to_representation(self, instance: AlphaTrigger) -> dict:
        """转换为表示"""
        # 转换证伪条件
        invalidation_conditions = []
        for condition in instance.invalidation_conditions:
            invalidation_conditions.append({
                "condition_type": condition.condition_type.value,
                "indicator_code": condition.indicator_code,
                "threshold": condition.threshold,
                "direction": condition.direction,
                "time_limit_hours": condition.time_limit_hours,
                "custom_condition": condition.custom_condition,
            })

        return {
            "trigger_id": instance.trigger_id,
            "trigger_type": instance.trigger_type.value,
            "asset_code": instance.asset_code,
            "asset_class": instance.asset_class,
            "direction": instance.direction,
            "trigger_condition": instance.trigger_condition,
            "invalidation_conditions": invalidation_conditions,
            "strength": instance.strength.value,
            "confidence": instance.confidence,
            "status": instance.status.value,
            "thesis": instance.thesis,
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "triggered_at": instance.triggered_at.isoformat() if instance.triggered_at else None,
            "invalidated_at": instance.invalidated_at.isoformat() if instance.invalidated_at else None,
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
            "source_signal_id": instance.source_signal_id or "",
            "related_regime": instance.related_regime or "",
            "related_policy_level": instance.related_policy_level,
            "custom_data": instance.custom_data,
        }


class AlphaCandidateSerializer(serializers.Serializer):
    """
    Alpha 候选序列化器

    用于候选的查询和更新。
    """

    candidate_id = serializers.CharField(
        read_only=True,
        help_text="候选 ID"
    )

    trigger_id = serializers.CharField(
        read_only=True,
        help_text="触发器 ID"
    )

    asset_code = serializers.CharField(
        read_only=True,
        help_text="资产代码"
    )

    asset_class = serializers.CharField(
        read_only=True,
        help_text="资产类别"
    )

    direction = serializers.ChoiceField(
        choices=["LONG", "SHORT", "NEUTRAL"],
        read_only=True,
        help_text="方向"
    )

    strength = SignalStrengthSerializer(
        read_only=True,
        help_text="信号强度"
    )

    confidence = serializers.FloatField(
        read_only=True,
        help_text="置信度"
    )

    status = CandidateStatusSerializer(
        read_only=True,
        help_text="状态"
    )

    thesis = serializers.CharField(
        read_only=True,
        help_text="投资论点"
    )

    entry_zone = serializers.DictField(
        read_only=True,
        help_text="入场区域"
    )

    exit_zone = serializers.DictField(
        read_only=True,
        help_text="出场区域"
    )

    time_horizon = serializers.IntegerField(
        read_only=True,
        help_text="时间窗口（天）"
    )

    expected_return = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="预期收益率"
    )

    risk_level = serializers.ChoiceField(
        choices=["LOW", "MEDIUM", "HIGH", "VERY_HIGH"],
        read_only=True,
        help_text="风险等级"
    )

    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="创建时间"
    )

    updated_at = serializers.DateTimeField(
        read_only=True,
        help_text="更新时间"
    )

    status_changed_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="状态变更时间"
    )

    promoted_to_signal_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="提升为信号的时间"
    )

    custom_data = serializers.DictField(
        read_only=True,
        help_text="自定义数据"
    )

    # 新增字段：首页主流程闭环改造
    last_decision_request_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="最后决策请求 ID"
    )

    last_execution_status = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="最后执行状态"
    )

    is_executed = serializers.BooleanField(
        read_only=True,
        help_text="是否已执行"
    )

    has_decision_request = serializers.BooleanField(
        read_only=True,
        help_text="是否有关联的决策请求"
    )

    def to_representation(self, instance: AlphaCandidate) -> dict:
        """转换为表示"""
        return {
            "candidate_id": instance.candidate_id,
            "trigger_id": instance.trigger_id,
            "asset_code": instance.asset_code,
            "asset_class": instance.asset_class,
            "direction": instance.direction,
            "strength": instance.strength.value,
            "confidence": instance.confidence,
            "status": instance.status.value,
            "thesis": instance.thesis,
            "entry_zone": instance.entry_zone,
            "exit_zone": instance.exit_zone,
            "time_horizon": instance.time_horizon,
            "expected_return": instance.expected_return,
            "risk_level": instance.risk_level,
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
            "status_changed_at": instance.status_changed_at.isoformat() if instance.status_changed_at else None,
            "promoted_to_signal_at": instance.promoted_to_signal_at.isoformat() if instance.promoted_to_signal_at else None,
            "custom_data": instance.custom_data,
            # 新增字段
            "last_decision_request_id": instance.last_decision_request_id,
            "last_execution_status": instance.last_execution_status,
            "is_executed": instance.is_executed,
            "has_decision_request": instance.has_decision_request,
        }


# ========== Request Serializers ==========


class CreateTriggerRequestSerializer(serializers.Serializer):
    """创建触发器请求序列化器"""

    trigger_type = serializers.ChoiceField(
        choices=[tt.value for tt in TriggerType],
        help_text="触发器类型"
    )

    asset_code = serializers.CharField(
        help_text="资产代码"
    )

    asset_class = serializers.CharField(
        help_text="资产类别"
    )

    direction = serializers.ChoiceField(
        choices=["LONG", "SHORT", "NEUTRAL"],
        help_text="方向"
    )

    trigger_condition = serializers.DictField(
        help_text="触发条件"
    )

    invalidation_conditions = InvalidationConditionSerializer(
        many=True,
        default=list,
        help_text="证伪条件列表"
    )

    confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="置信度"
    )

    thesis = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="投资论点"
    )

    expires_in_days = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="过期天数（可选）"
    )

    related_regime = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="相关 Regime"
    )

    related_policy_level = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="相关 Policy 档位"
    )

    source_signal_id = serializers.CharField(
        default="",
        required=False,
        allow_blank=True,
        help_text="源信号 ID"
    )


class CheckInvalidationRequestSerializer(serializers.Serializer):
    """检查证伪请求序列化器"""

    trigger_id = serializers.CharField(
        help_text="触发器 ID"
    )

    current_indicator_values = serializers.DictField(
        child=serializers.FloatField(),
        help_text="当前指标值"
    )

    current_regime = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="当前 Regime"
    )


class EvaluateTriggerRequestSerializer(serializers.Serializer):
    """评估触发器请求序列化器"""

    trigger_id = serializers.CharField(
        help_text="触发器 ID"
    )

    current_data = serializers.DictField(
        help_text="当前数据"
    )


class GenerateCandidateRequestSerializer(serializers.Serializer):
    """生成候选请求序列化器"""

    trigger_id = serializers.CharField(
        help_text="触发器 ID"
    )

    time_window_days = serializers.IntegerField(
        default=90,
        required=False,
        help_text="时间窗口天数"
    )


class UpdateCandidateStatusRequestSerializer(serializers.Serializer):
    """更新候选状态请求序列化器"""

    status = serializers.ChoiceField(
        choices=[cs.value for cs in CandidateStatus],
        help_text="新状态"
    )
