"""
Decision Rhythm DRF Serializers

决策频率约束和配额管理的 API 序列化器。

负责输入验证和输出格式化。
"""

from typing import Any, Dict, List, Optional

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    ExecutionStatus,
    ExecutionTarget,
    QuotaPeriod,
)

# ========== Enum Serializers ==========


@extend_schema_field(OpenApiTypes.STR)
class DecisionPrioritySerializer(serializers.Field):
    """决策优先级序列化器"""

    def to_representation(self, obj: DecisionPriority) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> DecisionPriority:
        try:
            return DecisionPriority(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid decision priority: {data}")


@extend_schema_field(OpenApiTypes.STR)
class QuotaPeriodSerializer(serializers.Field):
    """配额周期序列化器"""

    def to_representation(self, obj: QuotaPeriod) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> QuotaPeriod:
        try:
            return QuotaPeriod(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid quota period: {data}")


@extend_schema_field(OpenApiTypes.STR)
class ExecutionTargetSerializer(serializers.Field):
    """执行目标序列化器"""

    def to_representation(self, obj: ExecutionTarget) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> ExecutionTarget:
        try:
            return ExecutionTarget(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid execution target: {data}")


@extend_schema_field(OpenApiTypes.STR)
class ExecutionStatusSerializer(serializers.Field):
    """执行状态序列化器"""

    def to_representation(self, obj: ExecutionStatus) -> str:
        return obj.value

    def to_internal_value(self, data: str) -> ExecutionStatus:
        try:
            return ExecutionStatus(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid execution status: {data}")


# ========== Main Serializers ==========


class DecisionQuotaSerializer(serializers.Serializer):
    """
    决策配额序列化器

    用于配额的查询。
    """

    quota_id = serializers.CharField(read_only=True, help_text="配额 ID")

    period = QuotaPeriodSerializer(read_only=True, help_text="配额周期")

    max_decisions = serializers.IntegerField(read_only=True, help_text="最大决策次数")

    max_execution_count = serializers.IntegerField(read_only=True, help_text="最大执行次数")

    used_decisions = serializers.IntegerField(read_only=True, help_text="已使用决策次数")

    used_executions = serializers.IntegerField(read_only=True, help_text="已使用执行次数")

    remaining_decisions = serializers.IntegerField(read_only=True, help_text="剩余决策次数")

    remaining_executions = serializers.IntegerField(read_only=True, help_text="剩余执行次数")

    utilization_rate = serializers.FloatField(read_only=True, help_text="配额使用率")

    status = serializers.CharField(read_only=True, help_text="配额状态")

    period_start = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="周期开始时间"
    )

    period_end = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="周期结束时间"
    )

    created_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="创建时间")

    updated_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="更新时间")

    def to_representation(self, instance: DecisionQuota) -> dict:
        """转换为表示"""
        return {
            "quota_id": instance.quota_id,
            "period": instance.period.value,
            "max_decisions": instance.max_decisions,
            "max_execution_count": instance.max_execution_count,
            "used_decisions": instance.used_decisions,
            "used_executions": instance.used_executions,
            "remaining_decisions": instance.remaining_decisions,
            "remaining_executions": instance.remaining_executions,
            "utilization_rate": instance.utilization_rate,
            "status": instance.status.value,
            "period_start": instance.period_start.isoformat() if instance.period_start else None,
            "period_end": instance.period_end.isoformat() if instance.period_end else None,
            "created_at": instance.created_at.isoformat() if instance.created_at else None,
            "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
        }


class CooldownPeriodSerializer(serializers.Serializer):
    """
    冷却期序列化器

    用于冷却期的查询。
    """

    cooldown_id = serializers.CharField(read_only=True, help_text="冷却期 ID")

    asset_code = serializers.CharField(read_only=True, help_text="资产代码")

    last_decision_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="最后决策时间"
    )

    last_execution_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="最后执行时间"
    )

    min_decision_interval_hours = serializers.IntegerField(
        read_only=True, help_text="最小决策间隔（小时）"
    )

    min_execution_interval_hours = serializers.IntegerField(
        read_only=True, help_text="最小执行间隔（小时）"
    )

    same_asset_cooldown_hours = serializers.IntegerField(
        read_only=True, help_text="同资产冷却期（小时）"
    )

    is_decision_ready = serializers.BooleanField(read_only=True, help_text="是否可以决策")

    is_execution_ready = serializers.BooleanField(read_only=True, help_text="是否可以执行")

    decision_ready_in_hours = serializers.FloatField(read_only=True, help_text="距离可决策的小时数")

    execution_ready_in_hours = serializers.FloatField(
        read_only=True, help_text="距离可执行的小时数"
    )

    def to_representation(self, instance: CooldownPeriod) -> dict:
        """转换为表示"""
        return {
            "cooldown_id": instance.cooldown_id,
            "asset_code": instance.asset_code,
            "last_decision_at": (
                instance.last_decision_at.isoformat() if instance.last_decision_at else None
            ),
            "last_execution_at": (
                instance.last_execution_at.isoformat() if instance.last_execution_at else None
            ),
            "min_decision_interval_hours": instance.min_decision_interval_hours,
            "min_execution_interval_hours": instance.min_execution_interval_hours,
            "same_asset_cooldown_hours": instance.same_asset_cooldown_hours,
            "is_decision_ready": instance.is_decision_ready,
            "is_execution_ready": instance.is_execution_ready,
            "decision_ready_in_hours": instance.decision_ready_in_hours,
            "execution_ready_in_hours": instance.execution_ready_in_hours,
        }


class DecisionRequestSerializer(serializers.Serializer):
    """
    决策请求序列化器

    用于决策请求的查询。
    """

    request_id = serializers.CharField(read_only=True, help_text="请求 ID")

    asset_code = serializers.CharField(read_only=True, help_text="资产代码")

    asset_class = serializers.CharField(read_only=True, help_text="资产类别")

    direction = serializers.CharField(read_only=True, help_text="方向")

    priority = DecisionPrioritySerializer(read_only=True, help_text="优先级")

    priority_level = serializers.IntegerField(read_only=True, help_text="优先级等级")

    trigger_id = serializers.CharField(read_only=True, allow_null=True, help_text="触发器 ID")

    reason = serializers.CharField(read_only=True, help_text="原因")

    expected_confidence = serializers.FloatField(read_only=True, help_text="预期置信度")

    quantity = serializers.IntegerField(read_only=True, allow_null=True, help_text="数量")

    notional = serializers.FloatField(read_only=True, allow_null=True, help_text="名义金额")

    is_buy = serializers.BooleanField(read_only=True, help_text="是否买入")

    is_sell = serializers.BooleanField(read_only=True, help_text="是否卖出")

    is_expired = serializers.BooleanField(read_only=True, help_text="是否已过期")

    requested_at = serializers.DateTimeField(read_only=True, help_text="请求时间")

    expires_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="过期时间")

    # 新增字段：首页主流程闭环改造
    candidate_id = serializers.CharField(read_only=True, allow_null=True, help_text="关联的候选 ID")

    execution_target = ExecutionTargetSerializer(read_only=True, help_text="执行目标")

    execution_status = ExecutionStatusSerializer(read_only=True, help_text="执行状态")

    executed_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="执行时间")

    execution_ref = serializers.JSONField(read_only=True, allow_null=True, help_text="执行引用")

    is_executed = serializers.BooleanField(read_only=True, help_text="是否已执行")

    is_execution_pending = serializers.BooleanField(read_only=True, help_text="是否待执行")

    has_execution_target = serializers.BooleanField(read_only=True, help_text="是否有执行目标")

    def to_representation(self, instance: DecisionRequest) -> dict:
        """转换为表示"""
        return {
            "request_id": instance.request_id,
            "asset_code": instance.asset_code,
            "asset_class": instance.asset_class,
            "direction": instance.direction,
            "priority": instance.priority.value,
            "priority_level": instance.priority_level,
            "trigger_id": instance.trigger_id,
            "reason": instance.reason,
            "expected_confidence": instance.expected_confidence,
            "quantity": instance.quantity,
            "notional": instance.notional,
            "is_buy": instance.is_buy,
            "is_sell": instance.is_sell,
            "is_expired": instance.is_expired,
            "requested_at": instance.requested_at.isoformat(),
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
            # 新增字段
            "candidate_id": instance.candidate_id,
            "execution_target": instance.execution_target.value,
            "execution_status": instance.execution_status.value,
            "executed_at": instance.executed_at.isoformat() if instance.executed_at else None,
            "execution_ref": instance.execution_ref,
            "is_executed": instance.is_executed,
            "is_execution_pending": instance.is_execution_pending,
            "has_execution_target": instance.has_execution_target,
        }


# ========== Request Serializers ==========


class SubmitDecisionRequestRequestSerializer(serializers.Serializer):
    """提交决策请求序列化器"""

    account_id = serializers.CharField(
        default="default", required=False, allow_blank=False, help_text="账户 ID"
    )

    asset_code = serializers.CharField(help_text="资产代码")

    asset_class = serializers.CharField(help_text="资产类别")

    direction = serializers.ChoiceField(choices=["BUY", "SELL"], help_text="方向")

    priority = serializers.CharField(default=DecisionPriority.MEDIUM.value, help_text="优先级")

    trigger_id = serializers.CharField(
        default="", required=False, allow_blank=True, help_text="触发器 ID"
    )

    candidate_id = serializers.CharField(
        default="", required=False, allow_blank=True, help_text="候选 ID"
    )

    reason = serializers.CharField(default="", required=False, allow_blank=True, help_text="原因")

    expected_confidence = serializers.FloatField(
        default=0.0, min_value=0.0, max_value=1.0, required=False, help_text="预期置信度"
    )

    quantity = serializers.IntegerField(allow_null=True, required=False, help_text="数量")

    notional = serializers.FloatField(allow_null=True, required=False, help_text="名义金额")

    quota_period = serializers.CharField(
        default=QuotaPeriod.WEEKLY.value, required=False, help_text="使用的配额周期"
    )

    def validate_priority(self, value):
        normalized = str(value).strip().lower()
        valid = {dp.value for dp in DecisionPriority}
        if normalized not in valid:
            raise serializers.ValidationError(f"Invalid priority: {value}")
        return normalized

    def validate_quota_period(self, value):
        normalized = str(value).strip().lower()
        valid = {qp.value for qp in QuotaPeriod}
        if normalized not in valid:
            raise serializers.ValidationError(f"Invalid quota_period: {value}")
        return normalized


class SubmitBatchRequestRequestSerializer(serializers.Serializer):
    """批量提交决策请求序列化器"""

    requests = SubmitDecisionRequestRequestSerializer(many=True, help_text="决策请求列表")

    quota_period = serializers.CharField(
        default=QuotaPeriod.WEEKLY.value, required=False, help_text="使用的配额周期"
    )

    def validate_quota_period(self, value):
        normalized = str(value).strip().lower()
        valid = {qp.value for qp in QuotaPeriod}
        if normalized not in valid:
            raise serializers.ValidationError(f"Invalid quota_period: {value}")
        return normalized


class ResetQuotaRequestSerializer(serializers.Serializer):
    """重置配额请求序列化器"""

    account_id = serializers.CharField(default="default", required=False, help_text="账户 ID")

    period = serializers.ChoiceField(
        choices=[qp.value for qp in QuotaPeriod],
        required=False,
        allow_null=True,
        help_text="配额周期（空表示重置所有）",
    )


class TrendDataQuerySerializer(serializers.Serializer):
    """趋势数据查询序列化器"""

    days = serializers.IntegerField(default=7, required=False, help_text="天数 (7 或 30)")

    account_id = serializers.CharField(default="default", required=False, help_text="账户 ID")


class DecisionQuotaListQuerySerializer(serializers.Serializer):
    """配额列表查询序列化器"""

    period = serializers.ChoiceField(
        choices=[qp.value for qp in QuotaPeriod], required=False, help_text="配额周期"
    )
    account_id = serializers.CharField(required=False, allow_blank=False, help_text="账户 ID")


class DecisionQuotaByPeriodQuerySerializer(serializers.Serializer):
    """按周期查询配额的序列化器"""

    period = serializers.ChoiceField(
        choices=[qp.value for qp in QuotaPeriod],
        default=QuotaPeriod.WEEKLY.value,
        required=False,
        help_text="配额周期",
    )
    account_id = serializers.CharField(
        default="default", required=False, allow_blank=False, help_text="账户 ID"
    )


class CooldownByAssetQuerySerializer(serializers.Serializer):
    """按资产查询冷却期的序列化器"""

    direction = serializers.CharField(required=False, allow_blank=True, help_text="方向")


class CooldownRemainingHoursQuerySerializer(serializers.Serializer):
    """冷却剩余小时数查询序列化器"""

    asset_code = serializers.CharField(help_text="资产代码")
    direction = serializers.CharField(required=False, allow_blank=True, help_text="方向")


class DecisionRequestListQuerySerializer(serializers.Serializer):
    """决策请求列表查询序列化器"""

    days = serializers.IntegerField(default=30, required=False, min_value=1, help_text="查询天数")
    asset_code = serializers.CharField(required=False, allow_blank=True, help_text="资产代码")


class DecisionRequestStatisticsQuerySerializer(serializers.Serializer):
    """决策请求统计查询序列化器"""

    days = serializers.IntegerField(default=30, required=False, min_value=1, help_text="统计天数")


class PrecheckDecisionRequestSerializer(serializers.Serializer):
    """预检查请求序列化器"""

    candidate_id = serializers.CharField(help_text="候选 ID")


class ExecuteDecisionRequestSerializer(serializers.Serializer):
    """执行决策请求序列化器"""

    target = serializers.CharField(
        default=ExecutionTarget.SIMULATED.value, required=False, help_text="执行目标"
    )
    sim_account_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="模拟账户 ID"
    )
    portfolio_id = serializers.IntegerField(allow_null=True, required=False, help_text="组合 ID")
    asset_code = serializers.CharField(allow_blank=True, required=False, help_text="资产代码")
    action = serializers.CharField(default="buy", required=False, help_text="交易动作")
    quantity = serializers.IntegerField(allow_null=True, required=False, help_text="数量")
    price = serializers.FloatField(allow_null=True, required=False, help_text="价格")
    shares = serializers.IntegerField(allow_null=True, required=False, help_text="持仓股数")
    avg_cost = serializers.FloatField(allow_null=True, required=False, help_text="平均成本")
    current_price = serializers.FloatField(allow_null=True, required=False, help_text="当前价格")
    reason = serializers.CharField(
        default="按决策请求执行", required=False, allow_blank=True, help_text="执行原因"
    )

    def validate_target(self, value):
        normalized = str(value).strip().upper()
        valid = {target.value for target in ExecutionTarget}
        if normalized not in valid:
            raise serializers.ValidationError(f"Invalid target: {value}")
        return normalized


class CancelDecisionRequestSerializer(serializers.Serializer):
    """取消决策请求序列化器"""

    reason = serializers.CharField(
        default="", required=False, allow_blank=True, help_text="取消原因"
    )


class UpdateQuotaConfigRequestSerializer(serializers.Serializer):
    """更新配额配置请求序列化器"""

    account_id = serializers.CharField(default="default", required=False, help_text="账户 ID")
    period = serializers.CharField(help_text="配额周期")
    max_decisions = serializers.IntegerField(default=10, required=False, help_text="最大决策次数")
    max_executions = serializers.IntegerField(default=5, required=False, help_text="最大执行次数")

    def validate_period(self, value):
        normalized = str(value).strip().lower()
        valid = {qp.value for qp in QuotaPeriod}
        if normalized not in valid:
            raise serializers.ValidationError(f"Invalid period: {value}")
        return normalized
