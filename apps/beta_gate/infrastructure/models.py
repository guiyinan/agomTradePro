"""
Beta Gate Django ORM Models

硬闸门过滤的数据持久化模型。

简化版本，与现有 domain entities 兼容。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..domain.entities import GateStatus, RiskProfile


logger = logging.getLogger(__name__)


class GateConfigModel(models.Model):
    """
    闸门配置 ORM 模型

    存储不同风险画像的闸门配置。
    """

    # Risk Profile Choices
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    RISK_PROFILE_CHOICES = [
        (CONSERVATIVE, "保守型"),
        (BALANCED, "平衡型"),
        (AGGRESSIVE, "激进型"),
    ]

    # 字段定义
    config_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="配置唯一标识符"
    )

    risk_profile = models.CharField(
        max_length=20,
        choices=RISK_PROFILE_CHOICES,
        default=BALANCED,
        db_index=True,
        help_text="风险画像"
    )

    version = models.IntegerField(
        default=1,
        help_text="配置版本号"
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否激活"
    )

    # JSON 字段存储配置
    regime_constraints = models.JSONField(
        default=dict,
        help_text="Regime 约束配置"
    )

    policy_constraints = models.JSONField(
        default=dict,
        help_text="Policy 约束配置"
    )

    portfolio_constraints = models.JSONField(
        default=dict,
        help_text="组合约束配置"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    effective_date = models.DateField(
        default=timezone.now,
        help_text="生效日期"
    )

    expires_at = models.DateField(
        null=True,
        blank=True,
        help_text="过期日期（可选）"
    )

    class Meta:
        app_label = "beta_gate"
        db_table = "beta_gate_config"
        verbose_name = "Beta Gate 配置"
        verbose_name_plural = "Beta Gate 配置"
        ordering = ["-version", "risk_profile"]
        indexes = [
            models.Index(fields=["risk_profile", "is_active"]),
            models.Index(fields=["effective_date", "expires_at"]),
        ]

    def __str__(self):
        return f"GateConfig({self.config_id}, {self.risk_profile}, v{self.version})"

    def clean(self):
        """验证模型"""
        super().clean()

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return timezone.now().date() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """是否有效（激活且未过期）"""
        return self.is_active and not self.is_expired

    def to_domain(self):
        """转换为 Domain 层实体"""
        from ..domain.entities import GateConfig, RegimeConstraint, PolicyConstraint, PortfolioConstraint
        from datetime import date

        return GateConfig(
            config_id=self.config_id,
            risk_profile=RiskProfile(self.risk_profile),
            regime_constraint=RegimeConstraint.from_dict(self.regime_constraints),
            policy_constraint=PolicyConstraint.from_dict(self.policy_constraints),
            portfolio_constraint=PortfolioConstraint.from_dict(self.portfolio_constraints),
            version=self.version,
            is_active=self.is_active,
            effective_date=self.effective_date,
            expires_at=self.expires_at,
        )

    @classmethod
    def from_domain(cls, config):
        """从 Domain 层实体创建"""
        return cls(
            config_id=config.config_id,
            risk_profile=config.risk_profile.value,
            version=config.version,
            is_active=config.is_active,
            regime_constraints=config.regime_constraint.to_dict(),
            policy_constraints=config.policy_constraint.to_dict(),
            portfolio_constraints=config.portfolio_constraint.to_dict(),
            effective_date=config.effective_date,
            expires_at=config.expires_at,
        )


class GateDecisionModel(models.Model):
    """
    闸门决策 ORM 模型

    存储闸门决策历史记录。
    """

    # Status Choices
    PASSED = "passed"
    BLOCKED_REGIME = "blocked_regime"
    BLOCKED_POLICY = "blocked_policy"
    BLOCKED_RISK = "blocked_risk"
    BLOCKED_CONFIDENCE = "blocked_confidence"
    BLOCKED_PORTFOLIO = "blocked_portfolio"
    WATCH = "watch"
    STATUS_CHOICES = [
        (PASSED, "通过"),
        (BLOCKED_REGIME, "Regime拦截"),
        (BLOCKED_POLICY, "Policy拦截"),
        (BLOCKED_RISK, "风险拦截"),
        (BLOCKED_CONFIDENCE, "置信度拦截"),
        (BLOCKED_PORTFOLIO, "组合拦截"),
        (WATCH, "观察"),
    ]

    # 字段定义
    decision_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="决策唯一标识符"
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

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        help_text="决策状态"
    )

    current_regime = models.CharField(
        max_length=32,
        db_index=True,
        help_text="当前 Regime"
    )

    policy_level = models.IntegerField(
        help_text="Policy 档位"
    )

    regime_confidence = models.FloatField(
        help_text="Regime 置信度"
    )

    evaluation_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="评估详情"
    )

    evaluated_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="评估时间"
    )

    class Meta:
        app_label = "beta_gate"
        db_table = "beta_gate_decision"
        verbose_name = "Beta Gate 决策"
        verbose_name_plural = "Beta Gate 决策"
        ordering = ["-evaluated_at"]
        indexes = [
            models.Index(fields=["asset_code", "-evaluated_at"]),
            models.Index(fields=["current_regime", "-evaluated_at"]),
            models.Index(fields=["status", "-evaluated_at"]),
        ]

    def __str__(self):
        return f"GateDecision({self.asset_code}, {self.status}, {self.evaluated_at})"

    def to_domain(self):
        """转换为 Domain 层实体"""
        from ..domain.entities import GateDecision as DomainGateDecision, GateStatus

        details = self.evaluation_details or {}

        return DomainGateDecision(
            status=GateStatus(self.status),
            asset_code=self.asset_code,
            asset_class=self.asset_class,
            current_regime=self.current_regime,
            policy_level=self.policy_level,
            regime_confidence=self.regime_confidence,
            evaluated_at=self.evaluated_at,
            regime_check=details.get("regime_check", (True, "")),
            policy_check=details.get("policy_check", (True, "")),
            risk_check=details.get("risk_check", (True, "")),
            portfolio_check=details.get("portfolio_check", (True, "")),
            suggested_alternatives=details.get("suggested_alternatives", []),
            waiting_period_days=details.get("waiting_period_days"),
            score=details.get("score"),
        )

    @property
    def is_passed(self) -> bool:
        """是否通过"""
        return self.status == self.PASSED

    @property
    def is_blocked(self) -> bool:
        """是否被拦截"""
        return self.status.startswith("blocked_")

    @property
    def blocking_reason(self) -> str:
        """拦截原因"""
        if self.is_passed:
            return ""
        details = self.evaluation_details or {}
        return details.get("blocking_reason", "")


class VisibilityUniverseSnapshotModel(models.Model):
    """
    可见性宇宙快照 ORM 模型

    存储历史可见性宇宙快照。
    """

    snapshot_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="快照唯一标识符"
    )

    regime_snapshot_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Regime 快照 ID"
    )

    policy_snapshot_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Policy 快照 ID"
    )

    current_regime = models.CharField(
        max_length=32,
        db_index=True,
        help_text="当前 Regime"
    )

    policy_level = models.IntegerField(
        help_text="Policy 档位"
    )

    regime_confidence = models.FloatField(
        help_text="Regime 置信度"
    )

    risk_profile = models.CharField(
        max_length=20,
        choices=GateConfigModel.RISK_PROFILE_CHOICES,
        default=GateConfigModel.BALANCED,
        help_text="风险画像"
    )

    visible_asset_categories = models.JSONField(
        default=list,
        help_text="可见资产类别列表"
    )

    visible_strategies = models.JSONField(
        default=list,
        help_text="可见策略列表"
    )

    hard_exclusions = models.JSONField(
        default=list,
        help_text="硬排除列表"
    )

    watch_list = models.JSONField(
        default=list,
        help_text="观察列表"
    )

    as_of = models.DateField(
        default=timezone.now,
        help_text="截止日期"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="创建时间"
    )

    class Meta:
        app_label = "beta_gate"
        db_table = "beta_gate_universe_snapshot"
        verbose_name = "可见性宇宙快照"
        verbose_name_plural = "可见性宇宙快照"
        ordering = ["-as_of"]
        indexes = [
            models.Index(fields=["current_regime", "policy_level", "-as_of"]),
        ]

    def __str__(self):
        return f"UniverseSnapshot({self.snapshot_id}, {self.current_regime}, P{self.policy_level})"


# Custom QuerySets
class GateConfigQuerySet(models.QuerySet):
    """GateConfig 查询集扩展"""

    def active(self):
        """获取激活的配置"""
        return self.filter(is_active=True)

    def valid_at(self, timestamp):
        """获取指定时间有效的配置"""
        return self.filter(
            effective_date__lte=timestamp
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gte=timestamp)
        )

    def by_risk_profile(self, risk_profile):
        """按风险画像过滤"""
        return self.filter(risk_profile=risk_profile.value)


class GateDecisionQuerySet(models.QuerySet):
    """GateDecision 查询集扩展"""

    def passed(self):
        """获取通过的决策"""
        return self.filter(status=GateDecisionModel.PASSED)

    def blocked(self):
        """获取拦截的决策"""
        return self.exclude(status=GateDecisionModel.PASSED)

    def by_asset(self, asset_code):
        """按资产过滤"""
        return self.filter(asset_code=asset_code)

    def by_regime(self, regime):
        """按 Regime 过滤"""
        return self.filter(current_regime=regime)


# Custom Managers
GateConfigManager = models.Manager.from_queryset(GateConfigQuerySet)
GateDecisionManager = models.Manager.from_queryset(GateDecisionQuerySet)

# Assign managers
GateConfigModel.objects = GateConfigManager()
GateDecisionModel.objects = GateDecisionManager()
