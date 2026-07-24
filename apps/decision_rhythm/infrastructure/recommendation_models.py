"""Decision feature, unified recommendation, and execution-link ORM models."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from ..domain.entities import (
    DecisionFeatureSnapshot,
    RecommendationStatus,
    UnifiedRecommendation,
    UserDecisionAction,
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
        max_length=64, unique=True, db_index=True, help_text="快照唯一标识符"
    )

    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")

    snapshot_time = models.DateTimeField(db_index=True, help_text="快照时间")

    # Top-down 特征
    regime = models.CharField(max_length=64, default="", help_text="当前 Regime 状态")

    regime_confidence = models.FloatField(default=0.0, help_text="Regime 置信度")

    policy_level = models.CharField(max_length=32, default="", help_text="政策档位")

    beta_gate_passed = models.BooleanField(default=False, help_text="Beta Gate 是否通过")

    # Bottom-up 特征
    sentiment_score = models.FloatField(default=0.0, help_text="舆情分数")

    flow_score = models.FloatField(default=0.0, help_text="资金流向分数")

    technical_score = models.FloatField(default=0.0, help_text="技术面分数")

    fundamental_score = models.FloatField(default=0.0, help_text="基本面分数")

    alpha_model_score = models.FloatField(default=0.0, help_text="Alpha 模型分数")

    # 额外特征
    extra_features = models.JSONField(default=dict, help_text="额外特征")

    created_at = models.DateTimeField(auto_now_add=True, help_text="创建时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_feature_snapshot"
        verbose_name = "决策特征快照"
        verbose_name_plural = "决策特征快照"
        ordering = ["-snapshot_time"]
        indexes = [
            models.Index(fields=["security_code", "-snapshot_time"], name="idx_fsn_sec_time"),
        ]

    def __str__(self) -> str:
        return f"DecisionFeatureSnapshot({self.snapshot_id}, {self.security_code})"

    def save(self, *args: Any, **kwargs: Any) -> None:
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
    def from_domain(cls, snapshot: DecisionFeatureSnapshot) -> DecisionFeatureSnapshotModel:
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

    USER_ACTION_CHOICES = [
        (UserDecisionAction.PENDING.value, "待决策"),
        (UserDecisionAction.WATCHING.value, "观察中"),
        (UserDecisionAction.ADOPTED.value, "已采纳"),
        (UserDecisionAction.IGNORED.value, "已忽略"),
    ]

    # Side Choices
    SIDE_CHOICES = [
        ("BUY", "买入"),
        ("SELL", "卖出"),
        ("HOLD", "持有"),
    ]

    recommendation_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="推荐唯一标识符"
    )

    account_id = models.CharField(max_length=64, db_index=True, help_text="账户 ID")

    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")

    side = models.CharField(max_length=8, choices=SIDE_CHOICES, help_text="方向")

    # Top-down 特征
    regime = models.CharField(max_length=64, default="", help_text="当前 Regime 状态")

    regime_confidence = models.FloatField(default=0.0, help_text="Regime 置信度")

    policy_level = models.CharField(max_length=32, default="", help_text="政策档位")

    beta_gate_passed = models.BooleanField(
        default=False, db_index=True, help_text="Beta Gate 是否通过"
    )

    # Bottom-up 特征
    sentiment_score = models.FloatField(default=0.0, help_text="舆情分数")

    flow_score = models.FloatField(default=0.0, help_text="资金流向分数")

    technical_score = models.FloatField(default=0.0, help_text="技术面分数")

    fundamental_score = models.FloatField(default=0.0, help_text="基本面分数")

    alpha_model_score = models.FloatField(default=0.0, help_text="Alpha 模型分数")

    # 综合分数
    composite_score = models.FloatField(default=0.0, db_index=True, help_text="综合分数")

    confidence = models.FloatField(default=0.0, help_text="置信度")

    reason_codes = models.JSONField(default=list, help_text="原因代码列表")

    human_rationale = models.TextField(blank=True, help_text="人类可读理由")

    # 交易参数
    fair_value = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="公允价值"
    )

    entry_price_low = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="入场价格下限"
    )

    entry_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="入场价格上限"
    )

    target_price_low = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="目标价格下限"
    )

    target_price_high = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="目标价格上限"
    )

    stop_loss_price = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0"), help_text="止损价格"
    )

    position_pct = models.FloatField(default=5.0, help_text="建议仓位比例")

    suggested_quantity = models.IntegerField(default=0, help_text="建议数量")

    max_capital = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("50000"), help_text="最大资金量"
    )

    # 溯源
    source_signal_ids = models.JSONField(default=list, help_text="来源信号 ID 列表")

    source_candidate_ids = models.JSONField(default=list, help_text="来源候选 ID 列表")

    feature_snapshot = models.ForeignKey(
        DecisionFeatureSnapshotModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unified_recommendations",
        help_text="关联的特征快照",
    )

    # 状态
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=RecommendationStatus.NEW.value,
        db_index=True,
        help_text="推荐状态",
    )

    user_action = models.CharField(
        max_length=16,
        choices=USER_ACTION_CHOICES,
        default=UserDecisionAction.PENDING.value,
        db_index=True,
        help_text="用户决策动作",
    )

    user_action_note = models.TextField(blank=True, help_text="用户决策备注")

    user_action_at = models.DateTimeField(null=True, blank=True, help_text="用户动作时间")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="创建时间")

    updated_at = models.DateTimeField(auto_now=True, help_text="更新时间")

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_unified_recommendation"
        verbose_name = "统一推荐"
        verbose_name_plural = "统一推荐"
        ordering = ["-composite_score", "-created_at"]
        indexes = [
            models.Index(
                fields=["account_id", "security_code", "side", "-created_at"],
                name="idx_urec_acc_sec_side",
            ),
            models.Index(fields=["status", "-composite_score"], name="idx_urec_status_score"),
            models.Index(fields=["beta_gate_passed", "status"], name="idx_urec_gate_status"),
            # 复合索引：优化按账户+状态过滤 + 综合分排序的查询（M4 新增）
            models.Index(
                fields=["account_id", "status", "-composite_score"],
                name="idx_urec_acc_status_score",
            ),
            models.Index(
                fields=["account_id", "user_action", "-created_at"],
                name="idx_urec_acc_uaction_time",
            ),
        ]

    def __str__(self) -> str:
        return f"UnifiedRecommendation({self.recommendation_id}, {self.account_id}/{self.security_code}/{self.side})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.recommendation_id:
            self.recommendation_id = f"urec_{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)

    def clean(self) -> None:
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
            user_action=UserDecisionAction(self.user_action),
            user_action_note=self.user_action_note,
            user_action_at=self.user_action_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(
        cls,
        recommendation: UnifiedRecommendation,
        snapshot_model: DecisionFeatureSnapshotModel | None = None,
    ) -> UnifiedRecommendationModel:
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
            user_action=recommendation.user_action.value,
            user_action_note=recommendation.user_action_note,
            user_action_at=recommendation.user_action_at,
        )


class DecisionExecutionLinkModel(models.Model):
    """Link a manual account transaction to the system recommendation it followed."""

    TRANSACTION_SOURCE_CHOICES = [
        ("account_transaction", "账户成交"),
        ("simulated_trade", "模拟盘成交"),
    ]
    MATCH_METHOD_CHOICES = [
        ("auto", "自动匹配"),
        ("manual", "人工关联"),
        ("manual_only", "仅人工操作"),
    ]

    recommendation_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="关联的统一推荐 ID；manual_only 时为空",
    )
    transaction_id = models.IntegerField(db_index=True, help_text="account.TransactionModel ID")
    transaction_source = models.CharField(
        max_length=32,
        choices=TRANSACTION_SOURCE_CHOICES,
        default="account_transaction",
        db_index=True,
        help_text="成交来源：account.TransactionModel 或 simulated_trading.SimulatedTradeModel",
    )
    account_id = models.CharField(max_length=64, db_index=True, help_text="账户 ID")
    security_code = models.CharField(max_length=32, db_index=True, help_text="证券代码")
    actual_action = models.CharField(max_length=16, help_text="实际动作 buy/sell")
    match_method = models.CharField(
        max_length=32,
        choices=MATCH_METHOD_CHOICES,
        default="auto",
        db_index=True,
        help_text="匹配方式",
    )
    match_confidence = models.FloatField(default=0.0, help_text="匹配置信度")
    notes = models.TextField(blank=True, default="", help_text="备注")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "decision_rhythm"
        db_table = "decision_execution_link"
        verbose_name = "推荐执行关联"
        verbose_name_plural = "推荐执行关联"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["transaction_source", "transaction_id", "recommendation_id"],
                name="uq_decision_exec_link_tx_recommendation",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "security_code"], name="idx_exec_link_acc_sec"),
            models.Index(
                fields=["transaction_source", "-created_at"], name="idx_exec_link_src_time"
            ),
            models.Index(fields=["match_method", "-created_at"], name="idx_exec_link_method_time"),
        ]

    def __str__(self) -> str:
        target = self.recommendation_id or "manual_only"
        return f"{self.transaction_id} -> {target}"


__all__ = [
    "DecisionExecutionLinkModel",
    "DecisionFeatureSnapshotModel",
    "UnifiedRecommendationModel",
]
