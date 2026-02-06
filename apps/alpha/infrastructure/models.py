"""
Alpha Django ORM Models

Alpha 评分缓存和模型注册的数据持久化模型。
Domain 层实体映射到数据库表结构。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone


logger = logging.getLogger(__name__)


# ============================================================================
# QuerySet Classes (must be defined before Managers and Models)
# ============================================================================

class AlphaScoreCacheQuerySet(models.QuerySet):
    """AlphaScoreCache 查询集扩展"""

    def for_universe(self, universe_id: str):
        """按股票池过滤"""
        return self.filter(universe_id=universe_id)

    def for_date(self, trade_date):
        """按交易日期过滤"""
        return self.filter(intended_trade_date=trade_date)

    def from_provider(self, provider: str):
        """按提供者过滤"""
        return self.filter(provider_source=provider)

    def available(self):
        """获取可用的缓存"""
        return self.filter(status="available")

    def active_models(self):
        """获取来自激活模型的缓存"""
        # Simple filter for qlib provider - avoid circular reference
        return self.filter(provider_source="qlib")

    def latest_for_universe_and_date(self, universe_id: str, trade_date):
        """获取指定股票池和日期的最新缓存"""
        return self.filter(
            universe_id=universe_id,
            intended_trade_date=trade_date
        ).order_by("-created_at").first()


class QlibModelRegistryQuerySet(models.QuerySet):
    """QlibModelRegistry 查询集扩展"""

    def active(self):
        """获取激活的模型"""
        return self.filter(is_active=True)

    def for_universe(self, universe: str):
        """按股票池过滤"""
        return self.filter(universe=universe)

    def by_type(self, model_type: str):
        """按模型类型过滤"""
        return self.filter(model_type=model_type)

    def latest(self):
        """获取最新模型"""
        return self.order_by("-created_at").first()


# ============================================================================
# Manager Classes
# ============================================================================

AlphaScoreCacheManager = models.Manager.from_queryset(AlphaScoreCacheQuerySet)
QlibModelRegistryManager = models.Manager.from_queryset(QlibModelRegistryQuerySet)


# ============================================================================
# Model Classes
# ============================================================================

class AlphaScoreCacheModel(models.Model):
    """
    Alpha 评分缓存 ORM 模型

    存储 Alpha 计算结果，支持审计、版本追溯和 staleness 检查。

    Attributes:
        universe_id: 股票池标识
        intended_trade_date: 计划交易日期
        provider_source: 提供者来源（qlib/simple/etf）
        asof_date: 信号真实生成日期（避免前视偏差）
        model_id: 模型标识
        model_artifact_hash: 模型文件哈希
        feature_set_id: 特征集标识
        label_id: 标签标识
        data_version: 数据版本
        scores: 评分结果（JSON）
        status: 状态（available/degraded/unavailable）
        metrics_snapshot: 指标快照（JSON）
        created_at: 创建时间
        updated_at: 更新时间
    """

    # Custom Manager
    objects = AlphaScoreCacheManager()

    # Provider Choices
    PROVIDER_QLIB = "qlib"
    PROVIDER_SIMPLE = "simple"
    PROVIDER_ETF = "etf"
    PROVIDER_CACHE = "cache"

    PROVIDER_CHOICES = [
        (PROVIDER_QLIB, "Qlib"),
        (PROVIDER_SIMPLE, "Simple"),
        (PROVIDER_ETF, "ETF Fallback"),
        (PROVIDER_CACHE, "Cache"),
    ]

    # Status Choices
    STATUS_AVAILABLE = "available"
    STATUS_DEGRADED = "degraded"
    STATUS_UNAVAILABLE = "unavailable"

    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "可用"),
        (STATUS_DEGRADED, "降级"),
        (STATUS_UNAVAILABLE, "不可用"),
    ]

    # 主键信息
    universe_id = models.CharField(
        max_length=50,
        db_index=True,
        help_text="股票池标识"
    )

    intended_trade_date = models.DateField(
        db_index=True,
        help_text="计划交易日期"
    )

    provider_source = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        db_index=True,
        help_text="提供者来源"
    )

    # 时间对齐字段（审计必需）
    asof_date = models.DateField(
        db_index=True,
        help_text="信号真实生成日期"
    )

    # 模型版本信息（可追溯）
    model_id = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="模型标识"
    )

    model_artifact_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="模型文件哈希"
    )

    feature_set_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="特征集标识"
    )

    label_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="标签标识"
    )

    data_version = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="数据版本"
    )

    # 评分结果
    scores = models.JSONField(
        help_text="评分结果 [{code, score, rank, factors, confidence}, ...]"
    )

    # 质量指标
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_AVAILABLE,
        help_text="状态"
    )

    metrics_snapshot = models.JSONField(
        null=True,
        blank=True,
        help_text="指标快照"
    )

    # 审计字段
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
        app_label = "alpha"
        db_table = "alpha_score_cache"
        verbose_name = "Alpha 评分缓存"
        verbose_name_plural = "Alpha 评分缓存"
        ordering = ["-intended_trade_date", "-created_at"]
        # 唯一键：支持多模型同日共存
        unique_together = [
            ["universe_id", "intended_trade_date", "provider_source", "model_artifact_hash"]
        ]
        indexes = [
            models.Index(fields=["universe_id", "intended_trade_date"]),
            models.Index(fields=["provider_source", "status"]),
            models.Index(fields=["asof_date"]),
        ]

    def __str__(self):
        return f"{self.universe_id}@{self.intended_trade_date} ({self.provider_source})"

    def clean(self):
        """验证模型"""
        super().clean()

        # 验证日期逻辑
        if self.asof_date and self.intended_trade_date:
            if self.asof_date > self.intended_trade_date:
                raise ValidationError({
                    "asof_date": "信号生成日期不能晚于交易日期"
                })

        # 验证 scores 格式
        if self.scores and not isinstance(self.scores, list):
            raise ValidationError({"scores": "scores 必须是列表"})

    def is_stale(self, max_days: int = 2) -> bool:
        """
        检查数据是否过期

        Args:
            max_days: 最大可接受的天数

        Returns:
            是否过期
        """
        if not self.asof_date:
            return True

        # 使用当前日期（本地时区）而非 UTC 日期
        from datetime import date
        current_date = date.today()
        staleness = (current_date - self.asof_date).days
        return staleness > max_days

    def get_staleness_days(self) -> int:
        """
        获取数据陈旧天数

        Returns:
            陈旧天数
        """
        if not self.asof_date:
            return 999

        # 使用当前日期（本地时区）而非 UTC 日期
        from datetime import date
        current_date = date.today()
        return (current_date - self.asof_date).days


class QlibModelRegistryModel(models.Model):
    """
    Qlib 模型注册表 ORM 模型

    管理训练好的 Qlib 模型，支持版本控制、激活和回滚。

    Attributes:
        model_name: 模型名称
        artifact_hash: 模型文件哈希（主键）
        model_type: 模型类型（LGBModel/LSTM/Transformer）
        universe: 股票池
        train_config: 训练配置（JSON）
        feature_set_id: 特征集标识
        label_id: 标签标识
        data_version: 数据版本
        ic: IC 值
        icir: ICIR 值
        rank_ic: Rank IC 值
        model_path: 模型文件路径
        is_active: 是否激活
        created_at: 创建时间
        activated_at: 激活时间
        activated_by: 激活者
    """

    # Custom Manager
    objects = QlibModelRegistryManager()

    # Model Type Choices
    MODEL_LGB = "LGBModel"
    MODEL_LSTM = "LSTMModel"
    MODEL_TRANSFORMER = "TransformerModel"
    MODEL_MLP = "MLPModel"

    MODEL_TYPE_CHOICES = [
        (MODEL_LGB, "LightGBM"),
        (MODEL_LSTM, "LSTM"),
        (MODEL_TRANSFORMER, "Transformer"),
        (MODEL_MLP, "MLP"),
    ]

    # 模型标识
    model_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="模型名称"
    )

    artifact_hash = models.CharField(
        max_length=64,
        unique=True,
        primary_key=True,
        help_text="模型文件哈希"
    )

    # 训练配置
    model_type = models.CharField(
        max_length=30,
        choices=MODEL_TYPE_CHOICES,
        help_text="模型类型"
    )

    universe = models.CharField(
        max_length=20,
        help_text="股票池"
    )

    train_config = models.JSONField(
        help_text="训练配置"
    )

    # 特征和标签
    feature_set_id = models.CharField(
        max_length=50,
        help_text="特征集标识"
    )

    label_id = models.CharField(
        max_length=50,
        help_text="标签标识"
    )

    data_version = models.CharField(
        max_length=50,
        help_text="数据版本"
    )

    # 评估指标
    ic = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="IC 值"
    )

    icir = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="ICIR 值"
    )

    rank_ic = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Rank IC 值"
    )

    # 模型存储
    model_path = models.CharField(
        max_length=500,
        help_text="模型文件路径"
    )

    # 状态
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text="是否激活"
    )

    # 审计
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="激活时间"
    )

    activated_by = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="激活者"
    )

    class Meta:
        app_label = "alpha"
        db_table = "qlib_model_registry"
        verbose_name = "Qlib 模型注册"
        verbose_name_plural = "Qlib 模型注册"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["model_name", "is_active"]),
            models.Index(fields=["universe"]),
            models.Index(fields=["model_type"]),
        ]

    def __str__(self):
        active_flag = "ACTIVE" if self.is_active else "INACTIVE"
        return f"{self.model_name}@{self.artifact_hash[:8]} ({active_flag})"

    def activate(self, activated_by: str = "system") -> None:
        """
        激活模型

        会自动取消其他同类型模型的激活状态。

        Args:
            activated_by: 激活者标识
        """
        with transaction.atomic():
            # 取消其他激活的模型
            QlibModelRegistryModel.objects.filter(
                model_name=self.model_name,
                is_active=True
            ).update(is_active=False)

            # 激活当前模型
            self.is_active = True
            self.activated_at = timezone.now()
            self.activated_by = activated_by
            self.save()

    def deactivate(self) -> None:
        """取消激活"""
        self.is_active = False
        self.save()
