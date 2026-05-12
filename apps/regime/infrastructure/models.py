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

# Shared configuration models repatriated from shared.infrastructure.models

class RegimeEligibilityConfigModel(models.Model):
    """Regime 准入矩阵配置表"""

    ELIGIBILITY_CHOICES = [
        ('preferred', '优选'),
        ('neutral', '中性'),
        ('hostile', '敌对'),
    ]

    id = models.BigAutoField(primary_key=True)
    asset_class = models.CharField(
        max_length=50,
        verbose_name="资产类别"
    )
    regime = models.CharField(
        max_length=20,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation"
    )
    eligibility = models.CharField(
        max_length=20,
        choices=ELIGIBILITY_CHOICES,
        verbose_name="准入状态"
    )

    # 可选：权重配置
    weight = models.FloatField(
        default=1.0,
        verbose_name="权重",
        help_text="该资产在该 Regime 下的权重"
    )
    adjustment_factor = models.FloatField(
        default=1.0,
        verbose_name="调整因子",
        help_text="额外的权重调整系数"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'regime_eligibility_config'
        verbose_name = "Regime 准入矩阵配置"
        verbose_name_plural = "Regime 准入矩阵配置"
        unique_together = [['asset_class', 'regime']]
        indexes = [
            models.Index(fields=['asset_class', 'regime']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.asset_class} @ {self.regime}: {self.eligibility}"

class RiskParameterConfigModel(models.Model):
    """风险参数配置表"""

    PARAMETER_TYPE_CHOICES = [
        ('position_size', '仓位大小'),
        ('adjustment_factor', '调整因子'),
        ('stop_loss', '止损参数'),
        ('volatility', '波动率参数'),
        ('other', '其他'),
    ]

    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="参数键",
        help_text="如 position_p1, adjustment_recovery 等"
    )
    name = models.CharField(max_length=100, verbose_name="参数名称")
    parameter_type = models.CharField(
        max_length=20,
        choices=PARAMETER_TYPE_CHOICES,
        verbose_name="参数类型"
    )

    # 参数值（可以是数字、字符串或 JSON）
    value_float = models.FloatField(
        null=True,
        blank=True,
        verbose_name="数值"
    )
    value_string = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="字符串值"
    )
    value_json = models.JSONField(
        null=True,
        blank=True,
        verbose_name="JSON 值"
    )

    # 适用条件
    policy_level = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="适用政策档位",
        help_text="如 P0, P1, P2, P3，留空表示全部适用"
    )
    regime = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="适用 Regime",
        help_text="留空表示全部适用"
    )
    asset_class = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="适用资产类别",
        help_text="留空表示全部适用"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'risk_parameter_config'
        verbose_name = "风险参数配置"
        verbose_name_plural = "风险参数配置"

    def __str__(self):
        return f"{self.name} ({self.key})"

    def get_value(self):
        """获取参数值（自动判断类型）"""
        if self.value_float is not None:
            return self.value_float
        if self.value_string:
            return self.value_string
        if self.value_json:
            return self.value_json
        return None

