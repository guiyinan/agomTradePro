"""
Configuration Models for AgomSAAF

存储可在后台配置的参数，替代硬编码。
"""

from django.db import models


class AssetConfigModel(models.Model):
    """资产类别配置表"""

    CATEGORY_CHOICES = [
        ('equity', '股票'),
        ('bond', '债券'),
        ('commodity', '商品'),
        ('cash', '现金'),
    ]

    # 主键使用 asset_class 而不是自增 ID
    asset_class = models.CharField(
        max_length=50,
        unique=True,
        primary_key=True,
        verbose_name="资产类别代码"
    )
    display_name = models.CharField(max_length=100, verbose_name="显示名称")
    ticker_symbol = models.CharField(
        max_length=20,
        verbose_name="交易代码",
        help_text="如 000300.SH"
    )
    data_source = models.CharField(
        max_length=20,
        default='tushare',
        verbose_name="数据源"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        verbose_name="资产分类"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'asset_config'
        verbose_name = "资产类别配置"
        verbose_name_plural = "资产类别配置"

    def __str__(self):
        return f"{self.display_name} ({self.asset_class})"


class IndicatorConfigModel(models.Model):
    """宏观指标配置表"""

    CATEGORY_CHOICES = [
        ('growth', '增长指标'),
        ('inflation', '通胀指标'),
        ('monetary', '货币指标'),
        ('interest', '利率指标'),
        ('other', '其他'),
    ]

    code = models.CharField(
        max_length=50,
        unique=True,
        primary_key=True,
        verbose_name="指标代码"
    )
    name = models.CharField(max_length=100, verbose_name="指标名称")
    name_en = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="英文名称"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        verbose_name="指标分类"
    )
    unit = models.CharField(max_length=10, verbose_name="单位")

    # 可配置的阈值
    threshold_bullish = models.FloatField(
        null=True,
        blank=True,
        verbose_name="看涨阈值"
    )
    threshold_bearish = models.FloatField(
        null=True,
        blank=True,
        verbose_name="看跌阈值"
    )

    # 数据源配置
    data_source = models.CharField(
        max_length=20,
        default='akshare',
        verbose_name="数据源"
    )
    fetch_frequency = models.CharField(
        max_length=10,
        default='M',
        verbose_name="采集频率",
        help_text="D=日, W=周, M=月, Q=季, Y=年"
    )
    publication_lag_days = models.IntegerField(
        default=0,
        verbose_name="发布延迟天数"
    )

    description = models.TextField(blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'indicator_config'
        verbose_name = "宏观指标配置"
        verbose_name_plural = "宏观指标配置"

    def __str__(self):
        return f"{self.name} ({self.code})"


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


class FilterParameterConfigModel(models.Model):
    """滤波参数配置表"""

    FILTER_TYPE_CHOICES = [
        ('hp', 'HP 滤波'),
        ('kalman', 'Kalman 滤波'),
        ('ma', '移动平均'),
        ('other', '其他'),
    ]

    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="参数键",
        help_text="如 hp_monthly, kalman_macro 等"
    )
    name = models.CharField(max_length=100, verbose_name="参数名称")
    filter_type = models.CharField(
        max_length=20,
        choices=FILTER_TYPE_CHOICES,
        verbose_name="滤波类型"
    )

    # 滤波参数
    parameters = models.JSONField(
        verbose_name="滤波参数",
        help_text="如 {'lambda': 129600} 或 {'level_variance': 0.05}"
    )

    # 适用场景
    data_frequency = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="数据频率",
        help_text="D/W/M/Q/Y，留空表示不限"
    )
    indicator_category = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="适用指标分类",
        help_text="growth/inflation/等"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'filter_parameter_config'
        verbose_name = "滤波参数配置"
        verbose_name_plural = "滤波参数配置"

    def __str__(self):
        return f"{self.name} ({self.filter_type})"
