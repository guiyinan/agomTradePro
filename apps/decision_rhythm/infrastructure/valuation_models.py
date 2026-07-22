"""Valuation, recommendation, and approval ORM models."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError  # type: ignore[import-untyped]
from django.db import models  # type: ignore[import-untyped]
from django.utils import timezone  # type: ignore[import-untyped]

from ..domain.entities import (
    ExecutionApprovalRequest,
    InvestmentRecommendation,
    ValuationSnapshot,
)


class ValuationSnapshotModel(models.Model):  # type: ignore[misc]
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
        ("FALLBACK", "当前价兜底估值"),
        ("LEGACY", "历史数据"),
        ("CONSOLIDATED", "聚合估值"),
    ]

    snapshot_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="快照唯一标识符"
    )

    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")

    valuation_method = models.CharField(
        max_length=16, choices=VALUATION_METHOD_CHOICES, help_text="估值方法"
    )

    fair_value = models.DecimalField(max_digits=12, decimal_places=4, help_text="公允价值")

    entry_price_low = models.DecimalField(max_digits=12, decimal_places=4, help_text="入场价格下限")

    entry_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(max_digits=12, decimal_places=4, help_text="止损价格")

    calculated_at = models.DateTimeField(db_index=True, help_text="计算时间")

    input_parameters = models.JSONField(default=dict, help_text="输入参数")

    version = models.IntegerField(default=1, help_text="版本号")

    is_legacy = models.BooleanField(default=False, help_text="是否为历史数据迁移")

    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")

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

    def __str__(self) -> str:
        return (
            f"ValuationSnapshot({self.security_code}, {self.valuation_method}, {self.fair_value})"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
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
    def from_domain(cls, snapshot: ValuationSnapshot) -> ValuationSnapshotModel:
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


class InvestmentRecommendationModel(models.Model):  # type: ignore[misc]
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
        max_length=64, unique=True, db_index=True, help_text="建议唯一标识符"
    )

    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")

    account_id = models.CharField(
        max_length=64, db_index=True, default="default", help_text="账户 ID"
    )

    side = models.CharField(max_length=8, choices=SIDE_CHOICES, help_text="方向")

    confidence = models.FloatField(default=0.0, help_text="置信度 (0-1)")

    valuation_method = models.CharField(max_length=16, help_text="估值方法")

    fair_value = models.DecimalField(max_digits=12, decimal_places=4, help_text="公允价值")

    entry_price_low = models.DecimalField(max_digits=12, decimal_places=4, help_text="入场价格下限")

    entry_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(max_digits=12, decimal_places=4, help_text="止损价格")

    position_size_pct = models.FloatField(default=5.0, help_text="建议仓位比例")

    max_capital = models.DecimalField(
        max_digits=15, decimal_places=2, default=50000, help_text="最大资金量"
    )

    reason_codes = models.JSONField(default=list, help_text="原因代码列表")

    human_readable_rationale = models.TextField(blank=True, help_text="人类可读的理由")

    valuation_snapshot = models.ForeignKey(
        ValuationSnapshotModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recommendations",
        help_text="关联的估值快照",
    )

    source_recommendation_ids = models.JSONField(default=list, help_text="来源建议 ID 列表")

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="ACTIVE", db_index=True, help_text="建议状态"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="创建时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_investment_recommendation"
        verbose_name = "投资建议"
        verbose_name_plural = "投资建议"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["account_id", "security_code", "side", "-created_at"],
                name="idx_rec_acc_sec_side_created",
            ),
            models.Index(fields=["status", "-created_at"], name="idx_rec_status_created"),
        ]

    def __str__(self) -> str:
        return f"InvestmentRecommendation({self.security_code}, {self.side}, {self.confidence:.2f})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.recommendation_id:
            self.recommendation_id = f"rec_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def to_domain(self) -> InvestmentRecommendation:
        """
        转换为 Domain 层实体

        Returns:
            InvestmentRecommendation 实体
        """

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
            valuation_snapshot_id=(
                self.valuation_snapshot.snapshot_id if self.valuation_snapshot else ""
            ),
            source_recommendation_ids=self.source_recommendation_ids or [],
            created_at=self.created_at,
            status=self.status,
        )

    @classmethod
    def from_domain(cls, recommendation: InvestmentRecommendation) -> InvestmentRecommendationModel:
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


class ExecutionApprovalRequestModel(models.Model):  # type: ignore[misc]
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
        max_length=64, unique=True, db_index=True, help_text="请求唯一标识符"
    )

    recommendation = models.ForeignKey(
        InvestmentRecommendationModel,
        on_delete=models.CASCADE,
        related_name="approval_requests",
        null=True,
        blank=True,
        help_text="关联的投资建议（legacy，unified 路径可为空）",
    )

    account_id = models.CharField(max_length=64, db_index=True, help_text="账户 ID")

    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")

    side = models.CharField(max_length=8, choices=SIDE_CHOICES, help_text="方向")

    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default="PENDING",
        db_index=True,
        help_text="审批状态",
    )

    suggested_quantity = models.IntegerField(help_text="建议数量")

    market_price_at_review = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True, help_text="审批时的市场价格"
    )

    price_range_low = models.DecimalField(max_digits=12, decimal_places=4, help_text="价格区间下限")

    price_range_high = models.DecimalField(
        max_digits=12, decimal_places=4, help_text="价格区间上限"
    )

    stop_loss_price = models.DecimalField(max_digits=12, decimal_places=4, help_text="止损价格")

    risk_check_results = models.JSONField(default=dict, help_text="风控检查结果")

    reviewer_comments = models.TextField(blank=True, help_text="审批评论")

    regime_source = models.CharField(max_length=64, default="UNKNOWN", help_text="Regime 来源标识")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="创建时间")

    reviewed_at = models.DateTimeField(null=True, blank=True, help_text="审批时间")

    executed_at = models.DateTimeField(null=True, blank=True, help_text="执行时间")

    # 统一推荐关联字段（M1 新增）
    unified_recommendation = models.ForeignKey(
        "UnifiedRecommendationModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_v2",
        help_text="关联的统一推荐",
    )

    transition_plan = models.ForeignKey(
        "portfolio.PortfolioTransitionPlanModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
        help_text="关联的账户级调仓计划",
    )

    execution_params_json = models.JSONField(
        null=True, blank=True, default=dict, help_text="执行参数 JSON（价格区间、仓位等）"
    )

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_execution_approval_request"
        verbose_name = "执行审批请求"
        verbose_name_plural = "执行审批请求"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["account_id", "security_code", "side", "-created_at"],
                name="idx_apr_acc_sec_side_created",
            ),
            models.Index(fields=["approval_status", "-created_at"], name="idx_apr_status_created"),
            models.Index(fields=["regime_source"], name="idx_apr_regime_source"),
            models.Index(
                fields=["account_id", "security_code", "side"],
                name="idx_unique_pending_approval",
                condition=models.Q(approval_status="PENDING"),
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ExecutionApprovalRequest({self.security_code}, {self.side}, {self.approval_status})"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.request_id:
            self.request_id = f"apr_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def clean(self) -> None:
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

        from ..domain.entities import ApprovalStatus

        return ExecutionApprovalRequest(
            request_id=self.request_id,
            recommendation_id=(
                self.recommendation.recommendation_id
                if self.recommendation
                else (
                    self.unified_recommendation.recommendation_id
                    if self.unified_recommendation
                    else ""
                )
            ),
            plan_id=self.transition_plan.plan_id if self.transition_plan else None,
            account_id=self.account_id,
            security_code=self.security_code,
            side=self.side,
            approval_status=ApprovalStatus(self.approval_status),
            suggested_quantity=self.suggested_quantity,
            market_price_at_review=(
                Decimal(str(self.market_price_at_review)) if self.market_price_at_review else None
            ),
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
    def from_domain(
        cls, approval: ExecutionApprovalRequest, recommendation_model: InvestmentRecommendationModel
    ) -> ExecutionApprovalRequestModel:
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
            transition_plan=None,
            reviewed_at=approval.reviewed_at,
            executed_at=approval.executed_at,
        )


__all__ = [
    "ExecutionApprovalRequestModel",
    "InvestmentRecommendationModel",
    "ValuationSnapshotModel",
]
