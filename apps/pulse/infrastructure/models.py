from django.db import models


class PulseLog(models.Model):
    """Pulse 脉搏快照日志"""

    observed_at = models.DateField("观测日期", db_index=True)
    regime_context = models.CharField("当时的 Regime", max_length=20)

    # 4 维度分数
    growth_score = models.FloatField("增长脉搏", default=0.0)
    inflation_score = models.FloatField("通胀脉搏", default=0.0)
    liquidity_score = models.FloatField("流动性脉搏", default=0.0)
    sentiment_score = models.FloatField("情绪脉搏", default=0.0)

    # 综合
    composite_score = models.FloatField("综合分数")
    regime_strength = models.CharField("Regime 内强弱", max_length=20)

    # 转折预警
    transition_warning = models.BooleanField("转折预警", default=False)
    transition_direction = models.CharField(
        "预警方向", max_length=20, blank=True, null=True
    )

    # 明细 (JSON)
    indicator_readings = models.JSONField("指标明细", default=dict)
    transition_reasons = models.JSONField("预警原因", default=list)

    # 元数据
    data_source = models.CharField(max_length=20, default="calculated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pulse_log"
        ordering = ["-observed_at"]
        get_latest_by = "observed_at"

    def __str__(self) -> str:
        return f"{self.observed_at}: {self.regime_strength} ({self.composite_score:.2f})"


class PulseIndicatorConfigModel(models.Model):
    """Pulse 指标配置（存储在数据库中，可管理后台编辑）

    替代硬编码的指标定义和信号阈值。
    """

    DIMENSION_CHOICES = [
        ("growth", "增长"),
        ("inflation", "通胀"),
        ("liquidity", "流动性"),
        ("sentiment", "情绪"),
    ]

    FREQUENCY_CHOICES = [
        ("daily", "日频"),
        ("weekly", "周频"),
        ("monthly", "月频"),
    ]

    SIGNAL_TYPE_CHOICES = [
        ("zscore", "Z-Score"),
        ("level", "绝对水平"),
        ("pct_change", "涨跌幅"),
    ]

    indicator_code = models.CharField(
        "指标代码", max_length=50, unique=True,
        help_text="对应 macro 模块的指标代码，如 CN_TERM_SPREAD_10Y2Y",
    )
    indicator_name = models.CharField("指标名称", max_length=100)
    dimension = models.CharField(
        "所属维度", max_length=20, choices=DIMENSION_CHOICES,
    )
    frequency = models.CharField(
        "数据频率", max_length=20, choices=FREQUENCY_CHOICES, default="daily",
    )
    weight = models.FloatField(
        "维度内权重", default=1.0,
        help_text="维度内各指标的权重，默认等权=1.0",
    )

    # 信号计算配置
    signal_type = models.CharField(
        "信号类型", max_length=20, choices=SIGNAL_TYPE_CHOICES, default="zscore",
    )
    bullish_threshold = models.FloatField(
        "Bullish 阈值", default=1.0,
        help_text="超过此阈值判定为 bullish",
    )
    bearish_threshold = models.FloatField(
        "Bearish 阈值", default=-1.0,
        help_text="低于此阈值判定为 bearish",
    )
    neutral_band = models.FloatField(
        "中性区间", default=0.5,
        help_text="|value| < neutral_band 时判定为 neutral",
    )
    signal_multiplier = models.FloatField(
        "信号乘数", default=0.4,
        help_text="z_score → signal_score 的乘数。负值表示逆向指标。",
    )

    # 管理
    is_active = models.BooleanField("是否启用", default=True)
    description = models.TextField("说明", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pulse_indicator_config"
        ordering = ["dimension", "indicator_code"]
        verbose_name = "Pulse 指标配置"
        verbose_name_plural = "Pulse 指标配置"

    def __str__(self) -> str:
        return f"[{self.dimension}] {self.indicator_name} ({self.indicator_code})"


class NavigatorAssetConfigModel(models.Model):
    """Regime Navigator 资产配置映射（存储在数据库中）

    存储每个 Regime → 资产类别的权重区间和推荐板块。
    """

    REGIME_CHOICES = [
        ("Recovery", "复苏"),
        ("Overheat", "过热"),
        ("Stagflation", "滞胀"),
        ("Deflation", "通缩"),
    ]

    regime_name = models.CharField(
        "Regime 名称", max_length=20, choices=REGIME_CHOICES,
    )

    # 资产权重区间 (JSON): {"equity": [0.5, 0.7], "bond": [0.15, 0.3], ...}
    asset_weight_ranges = models.JSONField(
        "资产权重区间",
        help_text='格式: {"equity": [0.5, 0.7], "bond": [0.15, 0.3], "commodity": [0.05, 0.15], "cash": [0.05, 0.15]}',
    )

    risk_budget = models.FloatField(
        "风险预算(仓位上限)", default=0.7,
        help_text="0-1 之间的值",
    )

    # 推荐板块和风格 (JSON)
    recommended_sectors = models.JSONField(
        "推荐板块", default=list,
        help_text='格式: ["消费", "科技", "金融"]',
    )
    benefiting_styles = models.JSONField(
        "受益风格", default=list,
        help_text='格式: ["成长", "中小盘"]',
    )

    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "navigator_asset_config"
        unique_together = [("regime_name", "is_active")]
        ordering = ["regime_name"]
        verbose_name = "Navigator 资产配置"
        verbose_name_plural = "Navigator 资产配置"

    def __str__(self) -> str:
        return f"{self.regime_name}: risk={self.risk_budget}"


class PulseWeightConfig(models.Model):
    """Pulse 指标权重整体配置"""

    name = models.CharField("配置名称", max_length=100)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pulse_weight_config"


class PulseIndicatorWeight(models.Model):
    """单个指标的权重配置（维度间或者维度内按需分配）"""

    config = models.ForeignKey(PulseWeightConfig, on_delete=models.CASCADE, related_name="weights")
    indicator_code = models.CharField("指标代码", max_length=50)
    dimension = models.CharField("维度", max_length=20)
    weight = models.FloatField("权重", default=1.0)
    is_enabled = models.BooleanField("是否启用", default=True)

    class Meta:
        db_table = "pulse_indicator_weight"

