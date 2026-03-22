"""
Decision Rhythm Django ORM Models

决策频率约束和配额管理的数据持久化模型。

Domain 层实体映射到数据库表结构。
"""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
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
    ExecutionTarget,
    ExecutionStatus,
    ApprovalStatus,
    RecommendationSide,
    ValuationSnapshot,
    InvestmentRecommendation,
    ExecutionApprovalRequest,
    RecommendationStatus,
    UnifiedRecommendation,
    DecisionFeatureSnapshot,
    ModelParamConfig,
    ModelParamAuditLog,
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

    account_id = models.CharField(
        max_length=64,
        db_index=True,
        default="default",
        help_text="关联账户 ID，不同账户独立配额"
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
        app_label = "decision_rhythm"
        db_table = "decision_quota"
        verbose_name = "决策配额"
        verbose_name_plural = "决策配额"
        ordering = ["account_id", "period"]
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "period"],
                name="uq_quota_account_period",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "period"]),
            models.Index(fields=["period_end"]),
        ]

    def __str__(self):
        return f"DecisionQuota({self.account_id}/{self.period}, {self.used_decisions}/{self.max_decisions})"

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
            account_id=self.account_id,
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
            account_id=quota.account_id or "default",
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
        app_label = "decision_rhythm"
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
        candidate_id: 关联的候选 ID
        execution_target: 执行目标
        execution_status: 执行状态
        executed_at: 执行时间
        execution_ref: 执行引用
    """

    # Priority Choices
    PRIORITY_CHOICES = [
        (DecisionPriority.CRITICAL.value, "紧急"),
        (DecisionPriority.HIGH.value, "高"),
        (DecisionPriority.MEDIUM.value, "中"),
        (DecisionPriority.LOW.value, "低"),
        (DecisionPriority.INFO.value, "信息"),
    ]

    # Execution Target Choices
    EXECUTION_TARGET_CHOICES = [
        (ExecutionTarget.NONE.value, "无执行"),
        (ExecutionTarget.SIMULATED.value, "模拟盘执行"),
        (ExecutionTarget.ACCOUNT.value, "实盘执行"),
    ]

    # Execution Status Choices
    EXECUTION_STATUS_CHOICES = [
        (ExecutionStatus.PENDING.value, "待执行"),
        (ExecutionStatus.EXECUTED.value, "已执行"),
        (ExecutionStatus.FAILED.value, "执行失败"),
        (ExecutionStatus.CANCELLED.value, "已取消"),
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

    # 新增字段：首页主流程闭环改造
    candidate_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="关联的候选 ID"
    )

    execution_target = models.CharField(
        max_length=16,
        choices=EXECUTION_TARGET_CHOICES,
        default=ExecutionTarget.NONE.value,
        help_text="执行目标"
    )

    execution_status = models.CharField(
        max_length=16,
        choices=EXECUTION_STATUS_CHOICES,
        default=ExecutionStatus.PENDING.value,
        db_index=True,
        help_text="执行状态"
    )

    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="执行时间"
    )

    execution_ref = models.JSONField(
        null=True,
        blank=True,
        help_text="执行引用（如 trade_id, position_id 等）"
    )

    # 统一推荐关联字段（M1 新增）
    unified_recommendation = models.ForeignKey(
        "UnifiedRecommendationModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_requests",
        help_text="关联的统一推荐"
    )

    feature_snapshot = models.ForeignKey(
        "DecisionFeatureSnapshotModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_requests",
        help_text="关联的特征快照"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_request"
        verbose_name = "决策请求"
        verbose_name_plural = "决策请求"
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["asset_code", "-requested_at"]),
            models.Index(fields=["priority", "-requested_at"]),
            models.Index(fields=["trigger_id"]),
            models.Index(fields=["candidate_id"]),
            models.Index(fields=["execution_status"]),
            models.Index(fields=["unified_recommendation"]),
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

        # 验证执行状态一致性
        # EXECUTED 状态必须有 executed_at
        if self.execution_status == ExecutionStatus.EXECUTED.value and self.executed_at is None:
            raise ValidationError({
                "executed_at": "执行状态为 EXECUTED 时，执行时间不能为空"
            })

        # NONE 目标不应该有 execution_ref
        if self.execution_target == ExecutionTarget.NONE.value and self.execution_ref is not None:
            raise ValidationError({
                "execution_ref": "执行目标为 NONE 时，执行引用应为空"
            })

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
            # 新增字段
            candidate_id=self.candidate_id or None,
            execution_target=ExecutionTarget(self.execution_target),
            execution_status=ExecutionStatus(self.execution_status),
            executed_at=self.executed_at,
            execution_ref=self.execution_ref,
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
            # 新增字段
            candidate_id=request.candidate_id or "",
            execution_target=request.execution_target.value,
            execution_status=request.execution_status.value,
            executed_at=request.executed_at,
            execution_ref=request.execution_ref,
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
        app_label = "decision_rhythm"
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

    def save(self, *args, **kwargs):
        if not self.response_id:
            self.response_id = f"response_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

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


class ValuationSnapshotModel(models.Model):
    """
    估值快照 ORM 模型

    存储决策时的估值状态快照。

    Attributes:
        snapshot_id: 快照唯一标识
        security_code: 证券代码
        valuation_method: 估值方法
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        calculated_at: 计算时间
        input_parameters: 输入参数
        version: 版本号
        is_legacy: 是否为历史数据迁移
    """

    # Valuation Method Choices
    VALUATION_METHOD_CHOICES = [
        ("DCF", "现金流折现法"),
        ("PE_BAND", "PE 通道法"),
        ("PB_BAND", "PB 通道法"),
        ("PEG", "PEG 估值法"),
        ("DIVIDEND", "股息折现法"),
        ("COMPOSITE", "综合估值法"),
        ("LEGACY", "历史数据"),
        ("CONSOLIDATED", "聚合估值"),
    ]

    snapshot_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="快照唯一标识符"
    )

    security_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="证券代码"
    )

    valuation_method = models.CharField(
        max_length=16,
        choices=VALUATION_METHOD_CHOICES,
        help_text="估值方法"
    )

    fair_value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="公允价值"
    )

    entry_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="入场价格下限"
    )

    entry_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="止损价格"
    )

    calculated_at = models.DateTimeField(
        db_index=True,
        help_text="计算时间"
    )

    input_parameters = models.JSONField(
        default=dict,
        help_text="输入参数"
    )

    version = models.IntegerField(
        default=1,
        help_text="版本号"
    )

    is_legacy = models.BooleanField(
        default=False,
        help_text="是否为历史数据迁移"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_valuation_snapshot"
        verbose_name = "估值快照"
        verbose_name_plural = "估值快照"
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["security_code", "-calculated_at"], name="idx_val_sec_calc"),
            models.Index(fields=["valuation_method"], name="idx_val_method"),
        ]

    def __str__(self):
        return f"ValuationSnapshot({self.security_code}, {self.valuation_method}, {self.fair_value})"

    def save(self, *args, **kwargs):
        if not self.snapshot_id:
            self.snapshot_id = f"vs_{uuid.uuid4().hex[:12]}"
        if not self.calculated_at:
            self.calculated_at = timezone.now()
        super().save(*args, **kwargs)

    def to_domain(self) -> ValuationSnapshot:
        """
        转换为 Domain 层实体

        Returns:
            ValuationSnapshot 实体
        """
        from decimal import Decimal

        return ValuationSnapshot(
            snapshot_id=self.snapshot_id,
            security_code=self.security_code,
            valuation_method=self.valuation_method,
            fair_value=Decimal(str(self.fair_value)),
            entry_price_low=Decimal(str(self.entry_price_low)),
            entry_price_high=Decimal(str(self.entry_price_high)),
            target_price_low=Decimal(str(self.target_price_low)),
            target_price_high=Decimal(str(self.target_price_high)),
            stop_loss_price=Decimal(str(self.stop_loss_price)),
            calculated_at=self.calculated_at,
            input_parameters=self.input_parameters,
            version=self.version,
            is_legacy=self.is_legacy,
        )

    @classmethod
    def from_domain(cls, snapshot: ValuationSnapshot) -> "ValuationSnapshotModel":
        """
        从 Domain 层实体创建

        Args:
            snapshot: ValuationSnapshot 实体

        Returns:
            ValuationSnapshotModel 实例
        """
        return cls(
            snapshot_id=snapshot.snapshot_id,
            security_code=snapshot.security_code,
            valuation_method=snapshot.valuation_method,
            fair_value=snapshot.fair_value,
            entry_price_low=snapshot.entry_price_low,
            entry_price_high=snapshot.entry_price_high,
            target_price_low=snapshot.target_price_low,
            target_price_high=snapshot.target_price_high,
            stop_loss_price=snapshot.stop_loss_price,
            calculated_at=snapshot.calculated_at,
            input_parameters=snapshot.input_parameters,
            version=snapshot.version,
            is_legacy=snapshot.is_legacy,
        )


class InvestmentRecommendationModel(models.Model):
    """
    投资建议 ORM 模型

    存储完整的投资建议。

    Attributes:
        recommendation_id: 建议唯一标识
        security_code: 证券代码
        side: 方向
        confidence: 置信度
        valuation_method: 估值方法
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_size_pct: 建议仓位比例
        max_capital: 最大资金量
        reason_codes: 原因代码列表
        human_readable_rationale: 人类可读的理由
        valuation_snapshot: 关联的估值快照
        source_recommendation_ids: 来源建议 ID 列表
        status: 建议状态
    """

    # Side Choices
    SIDE_CHOICES = [
        ("BUY", "买入"),
        ("SELL", "卖出"),
        ("HOLD", "持有"),
    ]

    # Status Choices
    STATUS_CHOICES = [
        ("ACTIVE", "活跃"),
        ("CONSOLIDATED", "已聚合"),
        ("EXECUTED", "已执行"),
        ("EXPIRED", "已过期"),
        ("CANCELLED", "已取消"),
    ]

    recommendation_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="建议唯一标识符"
    )

    security_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="证券代码"
    )

    account_id = models.CharField(
        max_length=64,
        db_index=True,
        default="default",
        help_text="账户 ID"
    )

    side = models.CharField(
        max_length=8,
        choices=SIDE_CHOICES,
        help_text="方向"
    )

    confidence = models.FloatField(
        default=0.0,
        help_text="置信度 (0-1)"
    )

    valuation_method = models.CharField(
        max_length=16,
        help_text="估值方法"
    )

    fair_value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="公允价值"
    )

    entry_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="入场价格下限"
    )

    entry_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="止损价格"
    )

    position_size_pct = models.FloatField(
        default=5.0,
        help_text="建议仓位比例"
    )

    max_capital = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=50000,
        help_text="最大资金量"
    )

    reason_codes = models.JSONField(
        default=list,
        help_text="原因代码列表"
    )

    human_readable_rationale = models.TextField(
        blank=True,
        help_text="人类可读的理由"
    )

    valuation_snapshot = models.ForeignKey(
        ValuationSnapshotModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations",
        help_text="关联的估值快照"
    )

    source_recommendation_ids = models.JSONField(
        default=list,
        help_text="来源建议 ID 列表"
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="ACTIVE",
        db_index=True,
        help_text="建议状态"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_investment_recommendation"
        verbose_name = "投资建议"
        verbose_name_plural = "投资建议"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "security_code", "side", "-created_at"], name="idx_rec_acc_sec_side_created"),
            models.Index(fields=["status", "-created_at"], name="idx_rec_status_created"),
        ]

    def __str__(self):
        return f"InvestmentRecommendation({self.security_code}, {self.side}, {self.confidence:.2f})"

    def save(self, *args, **kwargs):
        if not self.recommendation_id:
            self.recommendation_id = f"rec_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def to_domain(self) -> InvestmentRecommendation:
        """
        转换为 Domain 层实体

        Returns:
            InvestmentRecommendation 实体
        """
        from decimal import Decimal

        return InvestmentRecommendation(
            recommendation_id=self.recommendation_id,
            security_code=self.security_code,
            side=self.side,
            confidence=self.confidence,
            valuation_method=self.valuation_method,
            fair_value=Decimal(str(self.fair_value)),
            entry_price_low=Decimal(str(self.entry_price_low)),
            entry_price_high=Decimal(str(self.entry_price_high)),
            target_price_low=Decimal(str(self.target_price_low)),
            target_price_high=Decimal(str(self.target_price_high)),
            stop_loss_price=Decimal(str(self.stop_loss_price)),
            position_size_pct=self.position_size_pct,
            max_capital=Decimal(str(self.max_capital)),
            reason_codes=self.reason_codes or [],
            human_readable_rationale=self.human_readable_rationale,
            account_id=self.account_id,
            valuation_snapshot_id=self.valuation_snapshot.snapshot_id if self.valuation_snapshot else "",
            source_recommendation_ids=self.source_recommendation_ids or [],
            created_at=self.created_at,
            status=self.status,
        )

    @classmethod
    def from_domain(cls, recommendation: InvestmentRecommendation) -> "InvestmentRecommendationModel":
        """
        从 Domain 层实体创建

        Args:
            recommendation: InvestmentRecommendation 实体

        Returns:
            InvestmentRecommendationModel 实例
        """
        return cls(
            recommendation_id=recommendation.recommendation_id,
            security_code=recommendation.security_code,
            account_id=recommendation.account_id,
            side=recommendation.side,
            confidence=recommendation.confidence,
            valuation_method=recommendation.valuation_method,
            fair_value=recommendation.fair_value,
            entry_price_low=recommendation.entry_price_low,
            entry_price_high=recommendation.entry_price_high,
            target_price_low=recommendation.target_price_low,
            target_price_high=recommendation.target_price_high,
            stop_loss_price=recommendation.stop_loss_price,
            position_size_pct=recommendation.position_size_pct,
            max_capital=recommendation.max_capital,
            reason_codes=recommendation.reason_codes,
            human_readable_rationale=recommendation.human_readable_rationale,
            source_recommendation_ids=recommendation.source_recommendation_ids,
            status=recommendation.status,
        )


class ExecutionApprovalRequestModel(models.Model):
    """
    执行审批请求 ORM 模型

    存储标准交易审批单。

    Attributes:
        request_id: 请求唯一标识
        recommendation: 关联的投资建议
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向
        approval_status: 审批状态
        suggested_quantity: 建议数量
        market_price_at_review: 审批时的市场价格
        price_range_low: 价格区间下限
        price_range_high: 价格区间上限
        stop_loss_price: 止损价格
        risk_check_results: 风控检查结果
        reviewer_comments: 审批评论
        regime_source: Regime 来源标识
        reviewed_at: 审批时间
        executed_at: 执行时间
    """

    # Approval Status Choices
    APPROVAL_STATUS_CHOICES = [
        ("DRAFT", "草稿"),
        ("PENDING", "待审批"),
        ("APPROVED", "已批准"),
        ("REJECTED", "已拒绝"),
        ("EXECUTED", "已执行"),
        ("FAILED", "执行失败"),
    ]

    # Side Choices
    SIDE_CHOICES = [
        ("BUY", "买入"),
        ("SELL", "卖出"),
        ("HOLD", "持有"),
    ]

    request_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="请求唯一标识符"
    )

    recommendation = models.ForeignKey(
        InvestmentRecommendationModel,
        on_delete=models.CASCADE,
        related_name="approval_requests",
        null=True,
        blank=True,
        help_text="关联的投资建议（legacy，unified 路径可为空）"
    )

    account_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="账户 ID"
    )

    security_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="证券代码"
    )

    side = models.CharField(
        max_length=8,
        choices=SIDE_CHOICES,
        help_text="方向"
    )

    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default="PENDING",
        db_index=True,
        help_text="审批状态"
    )

    suggested_quantity = models.IntegerField(
        help_text="建议数量"
    )

    market_price_at_review = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="审批时的市场价格"
    )

    price_range_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="价格区间下限"
    )

    price_range_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="价格区间上限"
    )

    stop_loss_price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="止损价格"
    )

    risk_check_results = models.JSONField(
        default=dict,
        help_text="风控检查结果"
    )

    reviewer_comments = models.TextField(
        blank=True,
        help_text="审批评论"
    )

    regime_source = models.CharField(
        max_length=64,
        default="UNKNOWN",
        help_text="Regime 来源标识"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="审批时间"
    )

    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="执行时间"
    )

    # 统一推荐关联字段（M1 新增）
    unified_recommendation = models.ForeignKey(
        "UnifiedRecommendationModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_v2",
        help_text="关联的统一推荐"
    )

    execution_params_json = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text="执行参数 JSON（价格区间、仓位等）"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_execution_approval_request"
        verbose_name = "执行审批请求"
        verbose_name_plural = "执行审批请求"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "security_code", "side", "-created_at"], name="idx_apr_acc_sec_side_created"),
            models.Index(fields=["approval_status", "-created_at"], name="idx_apr_status_created"),
            models.Index(fields=["regime_source"], name="idx_apr_regime_source"),
            models.Index(
                fields=["account_id", "security_code", "side"],
                name="idx_unique_pending_approval",
                condition=models.Q(approval_status="PENDING"),
            ),
        ]

    def __str__(self):
        return f"ExecutionApprovalRequest({self.security_code}, {self.side}, {self.approval_status})"

    def save(self, *args, **kwargs):
        if not self.request_id:
            self.request_id = f"apr_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证数量
        if self.suggested_quantity <= 0:
            raise ValidationError({"suggested_quantity": "建议数量必须大于 0"})

        # 验证价格区间
        if self.price_range_low > self.price_range_high:
            raise ValidationError({"price_range_low": "价格区间下限不能大于上限"})

    def to_domain(self) -> ExecutionApprovalRequest:
        """
        转换为 Domain 层实体

        Returns:
            ExecutionApprovalRequest 实体
        """
        from decimal import Decimal
        from ..domain.entities import ApprovalStatus

        return ExecutionApprovalRequest(
            request_id=self.request_id,
            recommendation_id=self.recommendation.recommendation_id if self.recommendation else "",
            account_id=self.account_id,
            security_code=self.security_code,
            side=self.side,
            approval_status=ApprovalStatus(self.approval_status),
            suggested_quantity=self.suggested_quantity,
            market_price_at_review=Decimal(str(self.market_price_at_review)) if self.market_price_at_review else None,
            price_range_low=Decimal(str(self.price_range_low)),
            price_range_high=Decimal(str(self.price_range_high)),
            stop_loss_price=Decimal(str(self.stop_loss_price)),
            risk_check_results=self.risk_check_results or {},
            reviewer_comments=self.reviewer_comments,
            regime_source=self.regime_source,
            created_at=self.created_at,
            reviewed_at=self.reviewed_at,
            executed_at=self.executed_at,
        )

    @classmethod
    def from_domain(cls, approval: ExecutionApprovalRequest, recommendation_model: InvestmentRecommendationModel) -> "ExecutionApprovalRequestModel":
        """
        从 Domain 层实体创建

        Args:
            approval: ExecutionApprovalRequest 实体
            recommendation_model: 关联的 InvestmentRecommendationModel

        Returns:
            ExecutionApprovalRequestModel 实例
        """
        return cls(
            request_id=approval.request_id,
            recommendation=recommendation_model,
            account_id=approval.account_id,
            security_code=approval.security_code,
            side=approval.side,
            approval_status=approval.approval_status.value,
            suggested_quantity=approval.suggested_quantity,
            market_price_at_review=approval.market_price_at_review,
            price_range_low=approval.price_range_low,
            price_range_high=approval.price_range_high,
            stop_loss_price=approval.stop_loss_price,
            risk_check_results=approval.risk_check_results,
            reviewer_comments=approval.reviewer_comments,
            regime_source=approval.regime_source,
            reviewed_at=approval.reviewed_at,
            executed_at=approval.executed_at,
        )


class DecisionFeatureSnapshotModel(models.Model):
    """
    决策特征快照 ORM 模型

    保存打分输入快照，支持回放与审计。

    Attributes:
        snapshot_id: 快照唯一标识
        security_code: 证券代码
        snapshot_time: 快照时间
        regime: 当前 Regime 状态
        regime_confidence: Regime 置信度
        policy_level: 政策档位
        beta_gate_passed: Beta Gate 是否通过
        sentiment_score: 舆情分数
        flow_score: 资金流向分数
        technical_score: 技术面分数
        fundamental_score: 基本面分数
        alpha_model_score: Alpha 模型分数
        extra_features: 额外特征
    """

    snapshot_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="快照唯一标识符"
    )

    security_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="证券代码"
    )

    snapshot_time = models.DateTimeField(
        db_index=True,
        help_text="快照时间"
    )

    # Top-down 特征
    regime = models.CharField(
        max_length=64,
        default="",
        help_text="当前 Regime 状态"
    )

    regime_confidence = models.FloatField(
        default=0.0,
        help_text="Regime 置信度"
    )

    policy_level = models.CharField(
        max_length=32,
        default="",
        help_text="政策档位"
    )

    beta_gate_passed = models.BooleanField(
        default=False,
        help_text="Beta Gate 是否通过"
    )

    # Bottom-up 特征
    sentiment_score = models.FloatField(
        default=0.0,
        help_text="舆情分数"
    )

    flow_score = models.FloatField(
        default=0.0,
        help_text="资金流向分数"
    )

    technical_score = models.FloatField(
        default=0.0,
        help_text="技术面分数"
    )

    fundamental_score = models.FloatField(
        default=0.0,
        help_text="基本面分数"
    )

    alpha_model_score = models.FloatField(
        default=0.0,
        help_text="Alpha 模型分数"
    )

    # 额外特征
    extra_features = models.JSONField(
        default=dict,
        help_text="额外特征"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_feature_snapshot"
        verbose_name = "决策特征快照"
        verbose_name_plural = "决策特征快照"
        ordering = ["-snapshot_time"]
        indexes = [
            models.Index(fields=["security_code", "-snapshot_time"], name="idx_fsn_sec_time"),
        ]

    def __str__(self):
        return f"DecisionFeatureSnapshot({self.snapshot_id}, {self.security_code})"

    def save(self, *args, **kwargs):
        if not self.snapshot_id:
            self.snapshot_id = f"fsn_{uuid.uuid4().hex[:12]}"
        if not self.snapshot_time:
            self.snapshot_time = timezone.now()
        super().save(*args, **kwargs)

    def to_domain(self) -> DecisionFeatureSnapshot:
        """转换为 Domain 层实体"""
        return DecisionFeatureSnapshot(
            snapshot_id=self.snapshot_id,
            security_code=self.security_code,
            snapshot_time=self.snapshot_time,
            regime=self.regime,
            regime_confidence=self.regime_confidence,
            policy_level=self.policy_level,
            beta_gate_passed=self.beta_gate_passed,
            sentiment_score=self.sentiment_score,
            flow_score=self.flow_score,
            technical_score=self.technical_score,
            fundamental_score=self.fundamental_score,
            alpha_model_score=self.alpha_model_score,
            extra_features=self.extra_features or {},
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, snapshot: DecisionFeatureSnapshot) -> "DecisionFeatureSnapshotModel":
        """从 Domain 层实体创建"""
        return cls(
            snapshot_id=snapshot.snapshot_id,
            security_code=snapshot.security_code,
            snapshot_time=snapshot.snapshot_time,
            regime=snapshot.regime,
            regime_confidence=snapshot.regime_confidence,
            policy_level=snapshot.policy_level,
            beta_gate_passed=snapshot.beta_gate_passed,
            sentiment_score=snapshot.sentiment_score,
            flow_score=snapshot.flow_score,
            technical_score=snapshot.technical_score,
            fundamental_score=snapshot.fundamental_score,
            alpha_model_score=snapshot.alpha_model_score,
            extra_features=snapshot.extra_features,
        )


class UnifiedRecommendationModel(models.Model):
    """
    统一推荐对象 ORM 模型

    融合 Top-down 和 Bottom-up 的统一推荐对象。

    Attributes:
        recommendation_id: 推荐唯一标识
        account_id: 账户 ID
        security_code: 证券代码
        side: 方向 (BUY/SELL/HOLD)
        regime: 当前 Regime 状态
        regime_confidence: Regime 置信度
        policy_level: 政策档位
        beta_gate_passed: Beta Gate 是否通过
        sentiment_score: 舆情分数
        flow_score: 资金流向分数
        technical_score: 技术面分数
        fundamental_score: 基本面分数
        alpha_model_score: Alpha 模型分数
        composite_score: 综合分数
        confidence: 置信度
        reason_codes: 原因代码列表
        human_rationale: 人类可读理由
        fair_value: 公允价值
        entry_price_low: 入场价格下限
        entry_price_high: 入场价格上限
        target_price_low: 目标价格下限
        target_price_high: 目标价格上限
        stop_loss_price: 止损价格
        position_pct: 建议仓位比例
        suggested_quantity: 建议数量
        max_capital: 最大资金量
        source_signal_ids: 来源信号 ID 列表
        source_candidate_ids: 来源候选 ID 列表
        feature_snapshot: 关联的特征快照
        status: 推荐状态
    """

    # Status Choices
    STATUS_CHOICES = [
        (RecommendationStatus.NEW.value, "新建"),
        (RecommendationStatus.REVIEWING.value, "审核中"),
        (RecommendationStatus.APPROVED.value, "已批准"),
        (RecommendationStatus.REJECTED.value, "已拒绝"),
        (RecommendationStatus.EXECUTED.value, "已执行"),
        (RecommendationStatus.FAILED.value, "执行失败"),
        (RecommendationStatus.CONFLICT.value, "冲突"),
    ]

    # Side Choices
    SIDE_CHOICES = [
        ("BUY", "买入"),
        ("SELL", "卖出"),
        ("HOLD", "持有"),
    ]

    recommendation_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="推荐唯一标识符"
    )

    account_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="账户 ID"
    )

    security_code = models.CharField(
        max_length=32,
        db_index=True,
        help_text="证券代码"
    )

    side = models.CharField(
        max_length=8,
        choices=SIDE_CHOICES,
        help_text="方向"
    )

    # Top-down 特征
    regime = models.CharField(
        max_length=64,
        default="",
        help_text="当前 Regime 状态"
    )

    regime_confidence = models.FloatField(
        default=0.0,
        help_text="Regime 置信度"
    )

    policy_level = models.CharField(
        max_length=32,
        default="",
        help_text="政策档位"
    )

    beta_gate_passed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Beta Gate 是否通过"
    )

    # Bottom-up 特征
    sentiment_score = models.FloatField(
        default=0.0,
        help_text="舆情分数"
    )

    flow_score = models.FloatField(
        default=0.0,
        help_text="资金流向分数"
    )

    technical_score = models.FloatField(
        default=0.0,
        help_text="技术面分数"
    )

    fundamental_score = models.FloatField(
        default=0.0,
        help_text="基本面分数"
    )

    alpha_model_score = models.FloatField(
        default=0.0,
        help_text="Alpha 模型分数"
    )

    # 综合分数
    composite_score = models.FloatField(
        default=0.0,
        db_index=True,
        help_text="综合分数"
    )

    confidence = models.FloatField(
        default=0.0,
        help_text="置信度"
    )

    reason_codes = models.JSONField(
        default=list,
        help_text="原因代码列表"
    )

    human_rationale = models.TextField(
        blank=True,
        help_text="人类可读理由"
    )

    # 交易参数
    fair_value = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="公允价值"
    )

    entry_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="入场价格下限"
    )

    entry_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="止损价格"
    )

    position_pct = models.FloatField(
        default=5.0,
        help_text="建议仓位比例"
    )

    suggested_quantity = models.IntegerField(
        default=0,
        help_text="建议数量"
    )

    max_capital = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("50000"),
        help_text="最大资金量"
    )

    # 溯源
    source_signal_ids = models.JSONField(
        default=list,
        help_text="来源信号 ID 列表"
    )

    source_candidate_ids = models.JSONField(
        default=list,
        help_text="来源候选 ID 列表"
    )

    feature_snapshot = models.ForeignKey(
        DecisionFeatureSnapshotModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unified_recommendations",
        help_text="关联的特征快照"
    )

    # 状态
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=RecommendationStatus.NEW.value,
        db_index=True,
        help_text="推荐状态"
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

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_unified_recommendation"
        verbose_name = "统一推荐"
        verbose_name_plural = "统一推荐"
        ordering = ["-composite_score", "-created_at"]
        indexes = [
            models.Index(fields=["account_id", "security_code", "side", "-created_at"], name="idx_urec_acc_sec_side"),
            models.Index(fields=["status", "-composite_score"], name="idx_urec_status_score"),
            models.Index(fields=["beta_gate_passed", "status"], name="idx_urec_gate_status"),
            # 复合索引：优化按账户+状态过滤 + 综合分排序的查询（M4 新增）
            models.Index(fields=["account_id", "status", "-composite_score"], name="idx_urec_acc_status_score"),
        ]

    def __str__(self):
        return f"UnifiedRecommendation({self.recommendation_id}, {self.account_id}/{self.security_code}/{self.side})"

    def save(self, *args, **kwargs):
        if not self.recommendation_id:
            self.recommendation_id = f"urec_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证置信度
        if not 0 <= self.confidence <= 1:
            raise ValidationError({"confidence": "置信度必须在 0-1 之间"})

        # 验证仓位比例
        if self.position_pct <= 0 or self.position_pct > 100:
            raise ValidationError({"position_pct": "仓位比例必须在 0-100 之间"})

    def to_domain(self) -> UnifiedRecommendation:
        """转换为 Domain 层实体"""
        return UnifiedRecommendation(
            recommendation_id=self.recommendation_id,
            account_id=self.account_id,
            security_code=self.security_code,
            side=self.side,
            regime=self.regime,
            regime_confidence=self.regime_confidence,
            policy_level=self.policy_level,
            beta_gate_passed=self.beta_gate_passed,
            sentiment_score=self.sentiment_score,
            flow_score=self.flow_score,
            technical_score=self.technical_score,
            fundamental_score=self.fundamental_score,
            alpha_model_score=self.alpha_model_score,
            composite_score=self.composite_score,
            confidence=self.confidence,
            reason_codes=self.reason_codes or [],
            human_rationale=self.human_rationale,
            fair_value=Decimal(str(self.fair_value)),
            entry_price_low=Decimal(str(self.entry_price_low)),
            entry_price_high=Decimal(str(self.entry_price_high)),
            target_price_low=Decimal(str(self.target_price_low)),
            target_price_high=Decimal(str(self.target_price_high)),
            stop_loss_price=Decimal(str(self.stop_loss_price)),
            position_pct=self.position_pct,
            suggested_quantity=self.suggested_quantity,
            max_capital=Decimal(str(self.max_capital)),
            source_signal_ids=self.source_signal_ids or [],
            source_candidate_ids=self.source_candidate_ids or [],
            feature_snapshot_id=self.feature_snapshot.snapshot_id if self.feature_snapshot else "",
            status=RecommendationStatus(self.status),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, recommendation: UnifiedRecommendation, snapshot_model: Optional[DecisionFeatureSnapshotModel] = None) -> "UnifiedRecommendationModel":
        """从 Domain 层实体创建"""
        return cls(
            recommendation_id=recommendation.recommendation_id,
            account_id=recommendation.account_id,
            security_code=recommendation.security_code,
            side=recommendation.side,
            regime=recommendation.regime,
            regime_confidence=recommendation.regime_confidence,
            policy_level=recommendation.policy_level,
            beta_gate_passed=recommendation.beta_gate_passed,
            sentiment_score=recommendation.sentiment_score,
            flow_score=recommendation.flow_score,
            technical_score=recommendation.technical_score,
            fundamental_score=recommendation.fundamental_score,
            alpha_model_score=recommendation.alpha_model_score,
            composite_score=recommendation.composite_score,
            confidence=recommendation.confidence,
            reason_codes=recommendation.reason_codes,
            human_rationale=recommendation.human_rationale,
            fair_value=recommendation.fair_value,
            entry_price_low=recommendation.entry_price_low,
            entry_price_high=recommendation.entry_price_high,
            target_price_low=recommendation.target_price_low,
            target_price_high=recommendation.target_price_high,
            stop_loss_price=recommendation.stop_loss_price,
            position_pct=recommendation.position_pct,
            suggested_quantity=recommendation.suggested_quantity,
            max_capital=recommendation.max_capital,
            source_signal_ids=recommendation.source_signal_ids,
            source_candidate_ids=recommendation.source_candidate_ids,
            feature_snapshot=snapshot_model,
            status=recommendation.status.value,
        )


class DecisionModelParamConfigModel(models.Model):
    """
    决策模型参数配置 ORM 模型

    保存推荐模型参数（按环境/版本）。

    Attributes:
        config_id: 配置唯一标识
        param_key: 参数键
        param_value: 参数值
        param_type: 参数类型 (float/int/str/bool)
        env: 环境 (dev/test/prod)
        version: 版本号
        is_active: 是否激活
        description: 参数描述
        updated_by: 最后修改人
        updated_reason: 变更说明
    """

    # Param Type Choices
    PARAM_TYPE_CHOICES = [
        ("float", "浮点数"),
        ("int", "整数"),
        ("str", "字符串"),
        ("bool", "布尔值"),
    ]

    # Environment Choices
    ENV_CHOICES = [
        ("dev", "开发环境"),
        ("test", "测试环境"),
        ("prod", "生产环境"),
    ]

    config_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="配置唯一标识符"
    )

    param_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text="参数键"
    )

    param_value = models.TextField(
        help_text="参数值"
    )

    param_type = models.CharField(
        max_length=16,
        choices=PARAM_TYPE_CHOICES,
        default="float",
        help_text="参数类型"
    )

    env = models.CharField(
        max_length=16,
        choices=ENV_CHOICES,
        default="dev",
        db_index=True,
        help_text="环境"
    )

    version = models.IntegerField(
        default=1,
        help_text="版本号"
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否激活"
    )

    description = models.TextField(
        blank=True,
        help_text="参数描述"
    )

    updated_by = models.CharField(
        max_length=128,
        default="",
        help_text="最后修改人"
    )

    updated_reason = models.TextField(
        blank=True,
        help_text="变更说明"
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
        app_label = "decision_rhythm"
        db_table = "decision_model_param_config"
        verbose_name = "决策模型参数配置"
        verbose_name_plural = "决策模型参数配置"
        ordering = ["env", "param_key"]
        indexes = [
            models.Index(fields=["env", "param_key", "is_active"], name="idx_param_env_key_active"),
            models.Index(fields=["param_key", "env", "-version"], name="idx_param_key_env_version"),
        ]

    def __str__(self):
        return f"ModelParamConfig({self.param_key}={self.param_value}, env={self.env})"

    def save(self, *args, **kwargs):
        if not self.config_id:
            self.config_id = f"mpc_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def to_domain(self) -> ModelParamConfig:
        """转换为 Domain 层实体"""
        return ModelParamConfig(
            config_id=self.config_id,
            param_key=self.param_key,
            param_value=self.param_value,
            param_type=self.param_type,
            env=self.env,
            version=self.version,
            is_active=self.is_active,
            description=self.description,
            updated_by=self.updated_by,
            updated_reason=self.updated_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, config: ModelParamConfig) -> "DecisionModelParamConfigModel":
        """从 Domain 层实体创建"""
        return cls(
            config_id=config.config_id,
            param_key=config.param_key,
            param_value=config.param_value,
            param_type=config.param_type,
            env=config.env,
            version=config.version,
            is_active=config.is_active,
            description=config.description,
            updated_by=config.updated_by,
            updated_reason=config.updated_reason,
        )


class DecisionModelParamAuditLogModel(models.Model):
    """
    决策模型参数审计日志 ORM 模型

    保存参数变更审计日志（前后值、操作者、时间、备注）。

    Attributes:
        log_id: 日志唯一标识
        param_key: 参数键
        old_value: 旧值
        new_value: 新值
        env: 环境
        changed_by: 变更人
        change_reason: 变更原因
        changed_at: 变更时间
    """

    # Environment Choices
    ENV_CHOICES = [
        ("dev", "开发环境"),
        ("test", "测试环境"),
        ("prod", "生产环境"),
    ]

    log_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="日志唯一标识符"
    )

    param_key = models.CharField(
        max_length=128,
        db_index=True,
        help_text="参数键"
    )

    old_value = models.TextField(
        help_text="旧值"
    )

    new_value = models.TextField(
        help_text="新值"
    )

    env = models.CharField(
        max_length=16,
        choices=ENV_CHOICES,
        default="dev",
        db_index=True,
        help_text="环境"
    )

    changed_by = models.CharField(
        max_length=128,
        default="",
        help_text="变更人"
    )

    change_reason = models.TextField(
        blank=True,
        help_text="变更原因"
    )

    changed_at = models.DateTimeField(
        db_index=True,
        help_text="变更时间"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_model_param_audit_log"
        verbose_name = "决策模型参数审计日志"
        verbose_name_plural = "决策模型参数审计日志"
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["param_key", "-changed_at"], name="idx_audit_key_time"),
            models.Index(fields=["env", "-changed_at"], name="idx_audit_env_time"),
        ]

    def __str__(self):
        return f"ModelParamAuditLog({self.param_key}, {self.old_value} -> {self.new_value})"

    def save(self, *args, **kwargs):
        if not self.log_id:
            self.log_id = f"mpal_{uuid.uuid4().hex[:12]}"
        if not self.changed_at:
            self.changed_at = timezone.now()
        super().save(*args, **kwargs)

    def to_domain(self) -> ModelParamAuditLog:
        """转换为 Domain 层实体"""
        return ModelParamAuditLog(
            log_id=self.log_id,
            param_key=self.param_key,
            old_value=self.old_value,
            new_value=self.new_value,
            env=self.env,
            changed_by=self.changed_by,
            change_reason=self.change_reason,
            changed_at=self.changed_at,
        )

    @classmethod
    def from_domain(cls, log: ModelParamAuditLog) -> "DecisionModelParamAuditLogModel":
        """从 Domain 层实体创建"""
        return cls(
            log_id=log.log_id,
            param_key=log.param_key,
            old_value=log.old_value,
            new_value=log.new_value,
            env=log.env,
            changed_by=log.changed_by,
            change_reason=log.change_reason,
            changed_at=log.changed_at,
        )
