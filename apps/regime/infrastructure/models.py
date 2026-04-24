"""
ORM Models for Regime Data.
"""

from django.db import models
from django.db.models import Q


class RegimeLog(models.Model):
    """Regime 判定日志"""

    observed_at = models.DateField(unique=True, db_index=True)
    growth_momentum_z = models.FloatField()
    inflation_momentum_z = models.FloatField()
    distribution = models.JSONField()
    dominant_regime = models.CharField(max_length=20)
    confidence = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "regime_log"
        ordering = ['-observed_at']
        indexes = [
            models.Index(fields=['dominant_regime']),
            models.Index(fields=['observed_at']),
        ]

    def __str__(self):
        return f"{self.observed_at} - {self.dominant_regime} ({self.confidence:.2f})"

    def get_dominant_regime_display(self):
        """获取 Regime 的中文显示名称"""
        names = {
            'Recovery': '复苏',
            'Overheat': '过热',
            'Stagflation': '滞胀',
            'Deflation': '通缩'
        }
        return names.get(self.dominant_regime, self.dominant_regime)


class RegimeThresholdConfig(models.Model):
    """Regime 阈值配置（主表）"""

    name = models.CharField("配置名称", max_length=100)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'regime_regimethresholdconfig'
        verbose_name = "Regime阈值配置"
        verbose_name_plural = "Regime阈值配置"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=Q(is_active=True),
                name='regime_single_active_threshold',
            )
        ]

    def __str__(self):
        status = "激活" if self.is_active else "未激活"
        return f"{self.name} ({status})"

    def validate_constraints(self, exclude=None):
        """Allow admin/form activation switches to validate before transactional toggles run."""
        if self.is_active:
            exclude = set(exclude or [])
            exclude.add("is_active")
        super().validate_constraints(exclude=exclude)


class RegimeIndicatorThreshold(models.Model):
    """指标阈值配置"""

    config = models.ForeignKey(
        RegimeThresholdConfig,
        on_delete=models.CASCADE,
        related_name='thresholds',
        verbose_name="配置"
    )

    indicator_code = models.CharField("指标代码", max_length=50)
    indicator_name = models.CharField("指标名称", max_length=100)

    # 阈值定义
    level_low = models.FloatField(
        "低水平阈值",
        null=True,
        blank=True,
        help_text="低水平阈值（如 PMI < 50 为收缩）"
    )
    level_high = models.FloatField(
        "高水平阈值",
        null=True,
        blank=True,
        help_text="高水平阈值（如 PMI > 50 为扩张）"
    )

    description = models.TextField("说明", blank=True)

    class Meta:
        db_table = 'regime_regimeindicatorthreshold'
        verbose_name = "指标阈值"
        verbose_name_plural = "指标阈值"
        ordering = ['indicator_code']

    def __str__(self):
        return f"{self.indicator_code}: low={self.level_low}, high={self.level_high}"


class RegimeTrendIndicator(models.Model):
    """趋势指标配置"""

    config = models.ForeignKey(
        RegimeThresholdConfig,
        on_delete=models.CASCADE,
        related_name='trend_indicators',
        verbose_name="配置"
    )

    indicator_code = models.CharField("指标代码", max_length=50)
    momentum_period = models.IntegerField(
        "动量周期",
        default=3,
        help_text="动量计算周期（月）"
    )
    trend_weight = models.FloatField(
        "趋势权重",
        default=0.3,
        help_text="趋势权重（0-1），用于调整 Regime 判定"
    )

    class Meta:
        db_table = 'regime_regimetrendindicator'
        verbose_name = "趋势指标"
        verbose_name_plural = "趋势指标"
        ordering = ['indicator_code']

    def __str__(self):
        return f"{self.indicator_code}: period={self.momentum_period}m, weight={self.trend_weight}"


class ActionRecommendationLog(models.Model):
    """联合行动建议历史记录"""
    observed_at = models.DateField("观测日期", db_index=True)
    regime_name = models.CharField("当期 Regime", max_length=20)
    pulse_strength = models.CharField("Pulse 强弱", max_length=20)
    
    # 资产权重 (JSON)
    asset_weights = models.JSONField("资产权重", default=dict)
    risk_budget_pct = models.FloatField("风险预算 %")
    
    # 其他推荐
    recommended_sectors = models.JSONField("推荐板块", default=list)
    benefiting_styles = models.JSONField("受益风格", default=list)

    # 决策安全契约
    must_not_use_for_decision = models.BooleanField("禁止用于决策", default=False)
    blocked_reason = models.TextField("阻断原因", blank=True, default="")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "action_recommendation_log"
        ordering = ["-observed_at"]

    def __str__(self):
        return f"{self.observed_at}: {self.regime_name} (risk: {self.risk_budget_pct}%)"
