"""
Decision Rhythm Django ORM Models

决策频率约束和配额管理的数据持久化模型。

Domain 层实体映射到数据库表结构。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..domain.entities import (
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    DecisionPriority,
    QuotaPeriod,
)


logger = logging.getLogger(__name__)


class DecisionQuotaModel(models.Model):
    """
    决策配额 ORM 模型

    存储决策配额配置和状态。

    Attributes:
        quota_id: 配额 ID
        period: 配额周期
        max_decisions: 最大决策次数
        max_execution_count: 最大执行次数
        used_decisions: 已使用决策次数
        used_executions: 已使用执行次数
        period_start: 周期开始时间
        period_end: 周期结束时间
        created_at: 创建时间
        updated_at: 更新时间
    """

    # Period Choices
    PERIOD_CHOICES = [
        (QuotaPeriod.DAILY.value, "每日"),
        (QuotaPeriod.WEEKLY.value, "每周"),
        (QuotaPeriod.MONTHLY.value, "每月"),
    ]

    # 字段定义
    quota_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="配额唯一标识符"
    )

    period = models.CharField(
        max_length=16,
        choices=PERIOD_CHOICES,
        db_index=True,
        help_text="配额周期"
    )

    max_decisions = models.IntegerField(
        default=10,
        help_text="最大决策次数"
    )

    max_execution_count = models.IntegerField(
        default=5,
        help_text="最大执行次数"
    )

    used_decisions = models.IntegerField(
        default=0,
        help_text="已使用决策次数"
    )

    used_executions = models.IntegerField(
        default=0,
        help_text="已使用执行次数"
    )

    period_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="周期开始时间"
    )

    period_end = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="周期结束时间"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "decision_quota"
        verbose_name = "决策配额"
        verbose_name_plural = "决策配额"
        ordering = ["period"]
        indexes = [
            models.Index(fields=["period"]),
            models.Index(fields=["period_end"]),
        ]

    def __str__(self):
        return f"DecisionQuota({self.period}, {self.used_decisions}/{self.max_decisions})"

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证最大决策数
        if self.max_decisions <= 0:
            raise ValidationError({"max_decisions": "最大决策次数必须大于 0"})

        # 验证已使用数
        if self.used_decisions < 0:
            raise ValidationError({"used_decisions": "已使用决策次数不能为负"})

        if self.used_executions < 0:
            raise ValidationError({"used_executions": "已使用执行次数不能为负"})

    def to_domain(self) -> DecisionQuota:
        """
        转换为 Domain 层实体

        Returns:
            DecisionQuota 实体
        """
        return DecisionQuota(
            quota_id=self.quota_id,
            period=QuotaPeriod(self.period),
            max_decisions=self.max_decisions,
            max_execution_count=self.max_execution_count,
            used_decisions=self.used_decisions,
            used_executions=self.used_executions,
            period_start=self.period_start,
            period_end=self.period_end,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, quota: DecisionQuota) -> "DecisionQuotaModel":
        """
        从 Domain 层实体创建

        Args:
            quota: DecisionQuota 实体

        Returns:
            DecisionQuotaModel 实例
        """
        return cls(
            quota_id=quota.quota_id,
            period=quota.period.value,
            max_decisions=quota.max_decisions,
            max_execution_count=quota.max_execution_count,
            used_decisions=quota.used_decisions,
            used_executions=quota.used_executions,
            period_start=quota.period_start,
            period_end=quota.period_end,
        )


class CooldownPeriodModel(models.Model):
    """
    冷却期 ORM 模型

    存储资产的冷却期状态。

    Attributes:
        cooldown_id: 冷却期 ID
        asset_code: 资产代码
        last_decision_at: 最后决策时间
        last_execution_at: 最后执行时间
        min_decision_interval_hours: 最小决策间隔（小时）
        min_execution_interval_hours: 最小执行间隔（小时）
        same_asset_cooldown_hours: 同资产冷却期（小时）
        created_at: 创建时间
    """

    # 字段定义
    cooldown_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="冷却期唯一标识符"
    )

    asset_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="资产代码"
    )

    last_decision_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后决策时间"
    )

    last_execution_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最后执行时间"
    )

    min_decision_interval_hours = models.IntegerField(
        default=24,
        help_text="最小决策间隔（小时）"
    )

    min_execution_interval_hours = models.IntegerField(
        default=48,
        help_text="最小执行间隔（小时）"
    )

    same_asset_cooldown_hours = models.IntegerField(
        default=72,
        help_text="同资产冷却期（小时）"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    class Meta:
        db_table = "cooldown_period"
        verbose_name = "冷却期"
        verbose_name_plural = "冷却期"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["asset_code"]),
        ]

    def __str__(self):
        return f"CooldownPeriod({self.asset_code})"

    def to_domain(self) -> CooldownPeriod:
        """
        转换为 Domain 层实体

        Returns:
            CooldownPeriod 实体
        """
        return CooldownPeriod(
            cooldown_id=self.cooldown_id,
            asset_code=self.asset_code,
            last_decision_at=self.last_decision_at,
            last_execution_at=self.last_execution_at,
            min_decision_interval_hours=self.min_decision_interval_hours,
            min_execution_interval_hours=self.min_execution_interval_hours,
            same_asset_cooldown_hours=self.same_asset_cooldown_hours,
        )

    @classmethod
    def from_domain(cls, cooldown: CooldownPeriod) -> "CooldownPeriodModel":
        """
        从 Domain 层实体创建

        Args:
            cooldown: CooldownPeriod 实体

        Returns:
            CooldownPeriodModel 实例
        """
        return cls(
            cooldown_id=cooldown.cooldown_id,
            asset_code=cooldown.asset_code,
            last_decision_at=cooldown.last_decision_at,
            last_execution_at=cooldown.last_execution_at,
            min_decision_interval_hours=cooldown.min_decision_interval_hours,
            min_execution_interval_hours=cooldown.min_execution_interval_hours,
            same_asset_cooldown_hours=cooldown.same_asset_cooldown_hours,
        )


class DecisionRequestModel(models.Model):
    """
    决策请求 ORM 模型

    存储决策请求历史。

    Attributes:
        request_id: 请求 ID
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        priority: 优先级
        trigger_id: 触发器 ID
        reason: 原因
        expected_confidence: 预期置信度
        quantity: 数量
        notional: 名义金额
        requested_at: 请求时间
        expires_at: 过期时间
    """

    # Priority Choices
    PRIORITY_CHOICES = [
        (DecisionPriority.CRITICAL.value, "紧急"),
        (DecisionPriority.HIGH.value, "高"),
        (DecisionPriority.MEDIUM.value, "中"),
        (DecisionPriority.LOW.value, "低"),
        (DecisionPriority.INFO.value, "信息"),
    ]

    # 字段定义
    request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="请求唯一标识符"
    )

    asset_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="资产代码"
    )

    asset_class = models.CharField(
        max_length=64,
        help_text="资产类别"
    )

    direction = models.CharField(
        max_length=8,
        help_text="方向"
    )

    priority = models.CharField(
        max_length=16,
        choices=PRIORITY_CHOICES,
        default=DecisionPriority.MEDIUM.value,
        help_text="优先级"
    )

    trigger_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="触发器 ID"
    )

    reason = models.TextField(
        blank=True,
        help_text="原因"
    )

    expected_confidence = models.FloatField(
        default=0.0,
        help_text="预期置信度"
    )

    quantity = models.IntegerField(
        null=True,
        blank=True,
        help_text="数量"
    )

    notional = models.FloatField(
        null=True,
        blank=True,
        help_text="名义金额"
    )

    requested_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="请求时间"
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="过期时间"
    )

    class Meta:
        db_table = "decision_request"
        verbose_name = "决策请求"
        verbose_name_plural = "决策请求"
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["asset_code", "-requested_at"]),
            models.Index(fields=["priority", "-requested_at"]),
            models.Index(fields=["trigger_id"]),
        ]

    def __str__(self):
        return f"DecisionRequest({self.request_id}, {self.asset_code}, {self.priority})"

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证置信度
        if not 0 <= self.expected_confidence <= 1:
            raise ValidationError({"expected_confidence": "置信度必须在 0-1 之间"})

        # 验证数量
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "数量必须大于 0"})

        # 验证名义金额
        if self.notional is not None and self.notional <= 0:
            raise ValidationError({"notional": "名义金额必须大于 0"})

    def to_domain(self) -> DecisionRequest:
        """
        转换为 Domain 层实体

        Returns:
            DecisionRequest 实体
        """
        return DecisionRequest(
            request_id=self.request_id,
            asset_code=self.asset_code,
            asset_class=self.asset_class,
            direction=self.direction,
            priority=DecisionPriority(self.priority),
            trigger_id=self.trigger_id or None,
            reason=self.reason,
            expected_confidence=self.expected_confidence,
            quantity=self.quantity,
            notional=self.notional,
            requested_at=self.requested_at,
            expires_at=self.expires_at,
        )

    @classmethod
    def from_domain(cls, request: DecisionRequest) -> "DecisionRequestModel":
        """
        从 Domain 层实体创建

        Args:
            request: DecisionRequest 实体

        Returns:
            DecisionRequestModel 实例
        """
        return cls(
            request_id=request.request_id,
            asset_code=request.asset_code,
            asset_class=request.asset_class,
            direction=request.direction,
            priority=request.priority.value,
            trigger_id=request.trigger_id or "",
            reason=request.reason,
            expected_confidence=request.expected_confidence,
            quantity=request.quantity,
            notional=request.notional,
            expires_at=request.expires_at,
        )


class DecisionResponseModel(models.Model):
    """
    决策响应 ORM 模型

    存储决策响应历史。

    Attributes:
        response_id: 响应 ID
        request_id: 关联的请求 ID
        approved: 是否批准
        approval_reason: 批准原因
        scheduled_at: 调度时间
        estimated_execution_at: 预计执行时间
        rejection_reason: 拒绝原因
        wait_until: 等待直到
        quota_status: 配额状态
        cooldown_status: 冷却状态
        responded_at: 响应时间
    """

    # 字段定义
    response_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="响应唯一标识符"
    )

    request = models.OneToOneField(
        DecisionRequestModel,
        on_delete=models.CASCADE,
        related_name="response",
        help_text="关联的决策请求"
    )

    approved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="是否批准"
    )

    approval_reason = models.TextField(
        blank=True,
        help_text="批准原因"
    )

    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="调度时间"
    )

    estimated_execution_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="预计执行时间"
    )

    rejection_reason = models.TextField(
        blank=True,
        help_text="拒绝原因"
    )

    wait_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="等待直到"
    )

    quota_status = models.JSONField(
        null=True,
        blank=True,
        help_text="配额状态"
    )

    cooldown_status = models.TextField(
        blank=True,
        help_text="冷却状态"
    )

    alternative_suggestions = models.JSONField(
        null=True,
        blank=True,
        help_text="替代建议"
    )

    responded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="响应时间"
    )

    class Meta:
        db_table = "decision_response"
        verbose_name = "决策响应"
        verbose_name_plural = "决策响应"
        ordering = ["-responded_at"]
        indexes = [
            models.Index(fields=["approved", "-responded_at"]),
        ]

    def __str__(self):
        status = "APPROVED" if self.approved else "REJECTED"
        return f"DecisionResponse({self.request_id}, {status})"

    def to_domain(self, request: DecisionRequest) -> DecisionResponse:
        """
        转换为 Domain 层实体

        Returns:
            DecisionResponse 实体
        """
        return DecisionResponse(
            request_id=self.request_id,
            approved=self.approved,
            approval_reason=self.approval_reason,
            scheduled_at=self.scheduled_at,
            estimated_execution_at=self.estimated_execution_at,
            rejection_reason=self.rejection_reason,
            wait_until=self.wait_until,
            alternative_suggestions=self.alternative_suggestions or [],
            quota_status=str(self.quota_status) if self.quota_status else None,
            cooldown_status=self.cooldown_status,
            responded_at=self.responded_at,
        )
