"""
资产分析模块 - Infrastructure 层数据模型

本模块包含 Django ORM 模型定义。
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class WeightConfigModel(models.Model):
    """
    多维度评分权重配置表

    存储不同资产类型、市场条件下的权重配置。
    """

    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="配置名称",
        help_text="如: default, policy_crisis, sentiment_extreme"
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="配置描述"
    )

    # 四大维度权重
    regime_weight = models.FloatField(
        default=0.40,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Regime 权重"
    )

    policy_weight = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Policy 权重"
    )

    sentiment_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Sentiment 权重"
    )

    signal_weight = models.FloatField(
        default=0.15,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Signal 权重"
    )

    # 适用条件（可选）
    asset_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="资产类型",
        help_text="为空表示通用配置"
    )

    market_condition = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="市场状态",
        help_text="如: crisis, extreme_sentiment"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="是否激活"
    )

    priority = models.IntegerField(
        default=0,
        verbose_name="优先级",
        help_text="数字越大优先级越高"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "asset_weight_config"
        verbose_name = "权重配置"
        verbose_name_plural = "权重配置"
        ordering = ["-priority", "-created_at"]

    def __str__(self):
        return f"{self.name} (R={self.regime_weight:.2f}, P={self.policy_weight:.2f})"

    def clean(self):
        """验证权重总和"""
        from django.core.exceptions import ValidationError

        total = (
            self.regime_weight +
            self.policy_weight +
            self.sentiment_weight +
            self.signal_weight
        )

        if abs(total - 1.0) > 0.01:
            raise ValidationError(f"权重总和必须为1.0，当前为 {total:.4f}")

    def save(self, *args, **kwargs):
        """保存前验证"""
        self.full_clean()
        super().save(*args, **kwargs)


class AssetScoreCache(models.Model):
    """
    资产评分缓存表

    缓存资产评分结果，避免重复计算。
    """

    asset_type = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产类型"
    )

    asset_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产代码"
    )

    asset_name = models.CharField(
        max_length=100,
        verbose_name="资产名称"
    )

    score_date = models.DateField(
        db_index=True,
        verbose_name="评分日期"
    )

    # 评分上下文
    regime = models.CharField(
        max_length=20,
        verbose_name="Regime"
    )

    policy_level = models.CharField(
        max_length=2,
        verbose_name="政策档位"
    )

    sentiment_index = models.FloatField(
        verbose_name="情绪指数"
    )

    # 各维度得分
    regime_score = models.FloatField(
        default=0.0,
        verbose_name="Regime 得分"
    )

    policy_score = models.FloatField(
        default=0.0,
        verbose_name="Policy 得分"
    )

    sentiment_score = models.FloatField(
        default=0.0,
        verbose_name="Sentiment 得分"
    )

    signal_score = models.FloatField(
        default=0.0,
        verbose_name="Signal 得分"
    )

    # 综合得分
    total_score = models.FloatField(
        default=0.0,
        db_index=True,
        verbose_name="综合得分"
    )

    rank = models.IntegerField(
        default=0,
        verbose_name="排名"
    )

    # 推荐信息
    allocation_percent = models.FloatField(
        default=0.0,
        verbose_name="推荐比例(%)"
    )

    risk_level = models.CharField(
        max_length=20,
        default="未知",
        verbose_name="风险等级"
    )

    # 自定义维度得分（JSON）
    custom_scores = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="自定义得分"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = "asset_score_cache"
        verbose_name = "资产评分缓存"
        verbose_name_plural = "资产评分缓存"
        unique_together = [("asset_type", "asset_code", "score_date")]
        ordering = ["-score_date", "-total_score"]
        indexes = [
            models.Index(fields=["score_date", "total_score"]),
        ]

    def __str__(self):
        return f"{self.asset_code} - {self.score_date} - {self.total_score:.1f}"
