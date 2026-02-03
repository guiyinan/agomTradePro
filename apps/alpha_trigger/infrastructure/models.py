"""
Alpha Trigger Django ORM Models

Alpha 事件触发的数据持久化模型。

Domain 层实体映射到数据库表结构。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..domain.entities import (
    AlphaTrigger,
    AlphaCandidate,
    TriggerType,
    TriggerStatus,
    SignalStrength,
    InvalidationCondition,
    CandidateStatus,
)


logger = logging.getLogger(__name__)


class AlphaTriggerModel(models.Model):
    """
    Alpha 触发器 ORM 模型

    存储 Alpha 触发器配置和状态。

    Attributes:
        trigger_id: 触发器 ID
        trigger_type: 触发器类型
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        trigger_condition: JSON - 触发条件
        invalidation_conditions: JSON - 证伪条件列表
        strength: 信号强度
        confidence: 置信度
        status: 状态
        thesis: 投资论点
        created_at: 创建时间
        triggered_at: 触发时间
        invalidated_at: 证伪时间
        expires_at: 过期时间
        source_signal_id: 源信号 ID
        related_regime: 相关 Regime
        related_policy_level: 相关 Policy 档位
        custom_data: JSON - 自定义数据
    """

    # Trigger Type Choices
    MOMENTUM_SIGNAL = "MOMENTUM_SIGNAL"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    REGIME_TRANSITION = "REGIME_TRANSITION"
    POLICY_CHANGE = "POLICY_CHANGE"
    CUSTOM = "CUSTOM"
    TRIGGER_TYPE_CHOICES = [
        (MOMENTUM_SIGNAL, "动量信号"),
        (MEAN_REVERSION, "均值回归"),
        (BREAKOUT, "突破"),
        (REGIME_TRANSITION, "Regime 转换"),
        (POLICY_CHANGE, "Policy 变化"),
        (CUSTOM, "自定义"),
    ]

    # Status Choices
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (ACTIVE, "活跃"),
        (TRIGGERED, "已触发"),
        (INVALIDATED, "已证伪"),
        (EXPIRED, "已过期"),
        (CANCELLED, "已取消"),
    ]

    # Strength Choices
    VERY_WEAK = "VERY_WEAK"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    VERY_STRONG = "VERY_STRONG"
    STRENGTH_CHOICES = [
        (VERY_WEAK, "非常弱"),
        (WEAK, "弱"),
        (MODERATE, "中等"),
        (STRONG, "强"),
        (VERY_STRONG, "非常强"),
    ]

    # Direction Choices
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    DIRECTION_CHOICES = [
        (LONG, "做多"),
        (SHORT, "做空"),
        (NEUTRAL, "中性"),
    ]

    # 字段定义
    trigger_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="触发器唯一标识符"
    )

    trigger_type = models.CharField(
        max_length=32,
        choices=TRIGGER_TYPE_CHOICES,
        default=MOMENTUM_SIGNAL,
        db_index=True,
        help_text="触发器类型"
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
        max_length=16,
        choices=DIRECTION_CHOICES,
        default=LONG,
        help_text="方向"
    )

    trigger_condition = models.JSONField(
        default=dict,
        help_text="触发条件"
    )

    invalidation_conditions = models.JSONField(
        default=list,
        help_text="证伪条件列表"
    )

    strength = models.CharField(
        max_length=16,
        choices=STRENGTH_CHOICES,
        default=MODERATE,
        help_text="信号强度"
    )

    confidence = models.FloatField(
        default=0.5,
        help_text="置信度 (0-1)"
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=ACTIVE,
        db_index=True,
        help_text="状态"
    )

    thesis = models.TextField(
        blank=True,
        help_text="投资论点"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    triggered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="触发时间"
    )

    invalidated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="证伪时间"
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="过期时间"
    )

    source_signal_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="源信号 ID"
    )

    related_regime = models.CharField(
        max_length=32,
        blank=True,
        help_text="相关 Regime"
    )

    related_policy_level = models.IntegerField(
        null=True,
        blank=True,
        help_text="相关 Policy 档位"
    )

    custom_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="自定义数据"
    )

    class Meta:
        db_table = "alpha_trigger"
        verbose_name = "Alpha 触发器"
        verbose_name_plural = "Alpha 触发器"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["asset_code", "status"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["trigger_type", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"AlphaTrigger({self.trigger_id}, {self.asset_code}, {self.status})"

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证置信度
        if not 0 <= self.confidence <= 1:
            raise ValidationError({"confidence": "置信度必须在 0-1 之间"})

        # 验证过期时间
        if self.expires_at and self.expires_at <= self.created_at:
            raise ValidationError({"expires_at": "过期时间必须晚于创建时间"})

    def to_domain(self) -> AlphaTrigger:
        """
        转换为 Domain 层实体

        Returns:
            AlphaTrigger 实体
        """
        # 转换证伪条件
        invalidation_conditions = [
            InvalidationCondition.from_dict(c)
            for c in self.invalidation_conditions
        ]

        return AlphaTrigger(
            trigger_id=self.trigger_id,
            trigger_type=TriggerType(self.trigger_type),
            asset_code=self.asset_code,
            asset_class=self.asset_class,
            direction=self.direction,
            trigger_condition=self.trigger_condition,
            invalidation_conditions=invalidation_conditions,
            strength=SignalStrength(self.strength),
            confidence=self.confidence,
            status=TriggerStatus(self.status),
            created_at=self.created_at,
            triggered_at=self.triggered_at,
            invalidated_at=self.invalidated_at,
            expires_at=self.expires_at,
            source_signal_id=self.source_signal_id or None,
            related_regime=self.related_regime or None,
            related_policy_level=self.related_policy_level,
            thesis=self.thesis,
            custom_data=self.custom_data,
        )

    @classmethod
    def from_domain(cls, trigger: AlphaTrigger) -> "AlphaTriggerModel":
        """
        从 Domain 层实体创建

        Args:
            trigger: AlphaTrigger 实体

        Returns:
            AlphaTriggerModel 实例
        """
        # 转换证伪条件
        invalidation_conditions = [
            c.to_dict()
            for c in trigger.invalidation_conditions
        ]

        return cls(
            trigger_id=trigger.trigger_id,
            trigger_type=trigger.trigger_type.value,
            asset_code=trigger.asset_code,
            asset_class=trigger.asset_class,
            direction=trigger.direction,
            trigger_condition=trigger.trigger_condition,
            invalidation_conditions=invalidation_conditions,
            strength=trigger.strength.value,
            confidence=trigger.confidence,
            status=trigger.status.value,
            thesis=trigger.thesis,
            created_at=trigger.created_at,
            triggered_at=trigger.triggered_at,
            invalidated_at=trigger.invalidated_at,
            expires_at=trigger.expires_at,
            source_signal_id=trigger.source_signal_id or "",
            related_regime=trigger.related_regime or "",
            related_policy_level=trigger.related_policy_level,
            custom_data=trigger.custom_data,
        )


class AlphaCandidateModel(models.Model):
    """
    Alpha 候选 ORM 模型

    存储从触发器生成的 Alpha 候选。

    Attributes:
        candidate_id: 候选 ID
        trigger_id: 触发器 ID
        asset_code: 资产代码
        asset_class: 资产类别
        direction: 方向
        strength: 信号强度
        confidence: 置信度
        status: 状态
        thesis: 投资论点
        entry_zone: JSON - 入场区域
        exit_zone: JSON - 出场区域
        time_horizon: 时间窗口（天）
        expected_return: 预期收益率
        risk_level: 风险等级
        created_at: 创建时间
        updated_at: 更新时间
        status_changed_at: 状态变更时间
        promoted_to_signal_at: 提升为信号的时间
        custom_data: JSON - 自定义数据
    """

    # Status Choices
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    ACTIONABLE = "ACTIONABLE"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    CANDIDATE_STATUS_CHOICES = [
        (WATCH, "观察"),
        (CANDIDATE, "候选"),
        (ACTIONABLE, "可操作"),
        (EXECUTED, "已执行"),
        (CANCELLED, "已取消"),
    ]

    # Strength Choices (same as trigger)
    VERY_WEAK = "VERY_WEAK"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    VERY_STRONG = "VERY_STRONG"
    STRENGTH_CHOICES = [
        (VERY_WEAK, "非常弱"),
        (WEAK, "弱"),
        (MODERATE, "中等"),
        (STRONG, "强"),
        (VERY_STRONG, "非常强"),
    ]

    # Risk Level Choices
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    RISK_LEVEL_CHOICES = [
        (LOW, "低"),
        (MEDIUM, "中"),
        (HIGH, "高"),
        (VERY_HIGH, "非常高"),
    ]

    # Direction Choices
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    DIRECTION_CHOICES = [
        (LONG, "做多"),
        (SHORT, "做空"),
        (NEUTRAL, "中性"),
    ]

    # 字段定义
    candidate_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="候选唯一标识符"
    )

    trigger_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="触发器 ID"
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
        max_length=16,
        choices=DIRECTION_CHOICES,
        default=LONG,
        help_text="方向"
    )

    strength = models.CharField(
        max_length=16,
        choices=STRENGTH_CHOICES,
        default=MODERATE,
        help_text="信号强度"
    )

    confidence = models.FloatField(
        default=0.5,
        help_text="置信度 (0-1)"
    )

    status = models.CharField(
        max_length=16,
        choices=CANDIDATE_STATUS_CHOICES,
        default=WATCH,
        db_index=True,
        help_text="状态"
    )

    thesis = models.TextField(
        blank=True,
        help_text="投资论点"
    )

    entry_zone = models.JSONField(
        default=dict,
        blank=True,
        help_text="入场区域"
    )

    exit_zone = models.JSONField(
        default=dict,
        blank=True,
        help_text="出场区域"
    )

    time_horizon = models.IntegerField(
        default=90,
        help_text="时间窗口（天）"
    )

    expected_return = models.FloatField(
        null=True,
        blank=True,
        help_text="预期收益率"
    )

    risk_level = models.CharField(
        max_length=16,
        choices=RISK_LEVEL_CHOICES,
        default=MEDIUM,
        help_text="风险等级"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    status_changed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="状态变更时间"
    )

    promoted_to_signal_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="提升为信号的时间"
    )

    custom_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="自定义数据"
    )

    class Meta:
        db_table = "alpha_candidate"
        verbose_name = "Alpha 候选"
        verbose_name_plural = "Alpha 候选"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["asset_code", "status"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["trigger_id"]),
        ]

    def __str__(self):
        return f"AlphaCandidate({self.candidate_id}, {self.asset_code}, {self.status})"

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证置信度
        if not 0 <= self.confidence <= 1:
            raise ValidationError({"confidence": "置信度必须在 0-1 之间"})

        # 验证时间窗口
        if self.time_horizon <= 0:
            raise ValidationError({"time_horizon": "时间窗口必须大于 0"})

    def to_domain(self) -> AlphaCandidate:
        """
        转换为 Domain 层实体

        Returns:
            AlphaCandidate 实体
        """
        return AlphaCandidate(
            candidate_id=self.candidate_id,
            trigger_id=self.trigger_id,
            asset_code=self.asset_code,
            asset_class=self.asset_class,
            direction=self.direction,
            strength=SignalStrength(self.strength),
            confidence=self.confidence,
            status=CandidateStatus(self.status),
            thesis=self.thesis,
            entry_zone=self.entry_zone,
            exit_zone=self.exit_zone,
            time_horizon=self.time_horizon,
            expected_return=self.expected_return,
            risk_level=self.risk_level,
            created_at=self.created_at,
            updated_at=self.updated_at,
            status_changed_at=self.status_changed_at,
            promoted_to_signal_at=self.promoted_to_signal_at,
            custom_data=self.custom_data,
        )

    @classmethod
    def from_domain(cls, candidate: AlphaCandidate) -> "AlphaCandidateModel":
        """
        从 Domain 层实体创建

        Args:
            candidate: AlphaCandidate 实体

        Returns:
            AlphaCandidateModel 实例
        """
        return cls(
            candidate_id=candidate.candidate_id,
            trigger_id=candidate.trigger_id,
            asset_code=candidate.asset_code,
            asset_class=candidate.asset_class,
            direction=candidate.direction,
            strength=candidate.strength.value,
            confidence=candidate.confidence,
            status=candidate.status.value,
            thesis=candidate.thesis,
            entry_zone=candidate.entry_zone,
            exit_zone=candidate.exit_zone,
            time_horizon=candidate.time_horizon,
            expected_return=candidate.expected_return,
            risk_level=candidate.risk_level,
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
            status_changed_at=candidate.status_changed_at,
            promoted_to_signal_at=candidate.promoted_to_signal_at,
            custom_data=candidate.custom_data,
        )


class AlphaTriggerQuerySet(models.QuerySet):
    """AlphaTrigger 查询集扩展"""

    def active(self):
        """获取活跃的触发器"""
        return self.filter(status=AlphaTriggerModel.ACTIVE)

    def triggered(self):
        """获取已触发的触发器"""
        return self.filter(status=AlphaTriggerModel.TRIGGERED)

    def by_asset(self, asset_code: str):
        """按资产过滤"""
        return self.filter(asset_code=asset_code)

    def by_type(self, trigger_type: TriggerType):
        """按类型过滤"""
        return self.filter(trigger_type=trigger_type.value)

    def by_regime(self, regime: str):
        """按相关 Regime 过滤"""
        return self.filter(related_regime=regime)

    def not_expired(self):
        """获取未过期的触发器"""
        return self.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

    def need_invalidation_check(self):
        """获取需要检查证伪的触发器"""
        return self.active().not_expired()


class AlphaCandidateQuerySet(models.QuerySet):
    """AlphaCandidate 查询集扩展"""

    def actionable(self):
        """获取可操作的候选"""
        return self.filter(status=AlphaCandidateModel.ACTIONABLE)

    def watch(self):
        """获取观察中的候选"""
        return self.filter(status=AlphaCandidateModel.WATCH)

    def candidate(self):
        """获取候选中的"""
        return self.filter(status=AlphaCandidateModel.CANDIDATE)

    def by_asset(self, asset_code: str):
        """按资产过滤"""
        return self.filter(asset_code=asset_code)

    def by_trigger(self, trigger_id: str):
        """按触发器过滤"""
        return self.filter(trigger_id=trigger_id)

    def by_strength(self, min_strength: SignalStrength):
        """按最小强度过滤"""
        strength_order = [
            AlphaCandidateModel.VERY_WEAK,
            AlphaCandidateModel.WEAK,
            AlphaCandidateModel.MODERATE,
            AlphaCandidateModel.STRONG,
            AlphaCandidateModel.VERY_STRONG,
        ]
        min_index = strength_order.index(min_strength.value)
        valid_strengths = strength_order[min_index:]
        return self.filter(strength__in=valid_strengths)


# 自定义 Manager
AlphaTriggerManager = models.Manager.from_queryset(AlphaTriggerQuerySet)
AlphaCandidateManager = models.Manager.from_queryset(AlphaCandidateQuerySet)


# 为模型添加自定义 Manager
AlphaTriggerModel.objects = AlphaTriggerManager()
AlphaCandidateModel.objects = AlphaCandidateManager()
