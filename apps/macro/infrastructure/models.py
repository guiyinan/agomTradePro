"""
ORM Models for Macro Data.

Django models for persisting macro indicator data.
Provider configuration is now managed exclusively by apps.data_center.
"""

from django.db import models


class MacroIndicator(models.Model):
    """宏观指标 ORM 模型"""

    PERIOD_TYPE_CHOICES = [
        ('D', '日'),      # 时点数据：某日收盘价、SHIBOR日利率
        ('W', '周'),      # 周度数据：周度高频数据
        ('M', '月'),      # 月度数据：PMI、CPI、M2
        ('Q', '季'),      # 季度数据：GDP
        ('H', '半'),      # 半年度数据：半年度财报
        ('Y', '年'),      # 年度数据：年度GDP
    ]

    # 扩展期间类型（支持 3M、6M、10Y 等期限类数据）
    EXTENDED_PERIOD_TYPES = {
        '2W': '双周',
        '2M': '双月',
        '10D': '旬',
        '3M': '3月期',
        '6M': '6月期',
        '1Y': '1年期',
        '5Y': '5年期',
        '10Y': '10年期',
        '20Y': '20年期',
        '30Y': '30年期',
    }

    code = models.CharField(max_length=50, db_index=True, help_text="指标代码")
    value = models.FloatField(help_text="指标值")  # 改用 FloatField 以更鲁棒地处理各种数据格式
    unit = models.CharField(max_length=50, default="", help_text="存储单位（货币类统一为元）")
    original_unit = models.CharField(max_length=50, default="", help_text="原始单位（数据源返回的单位，用于展示）")

    # 报告期：时点数据为观测日，期间数据为期末日
    reporting_period = models.DateField(
        db_index=True,
        help_text="报告期（时点数据=观测日，期间数据=期末日）"
    )

    # 期间类型：扩展为 CharField(max_length=10) 且移除 choices 约束
    # 支持标准类型 (D/W/M/Q/H/Y) 和扩展类型 (3M/6M/10Y/2W 等)
    period_type = models.CharField(
        max_length=10,
        default='D',
        help_text="期间类型（D=日,W=周,M=月,Q=季,H=半,Y=年,3M=3月期,10Y=10年期等）"
    )

    published_at = models.DateField(null=True, blank=True, help_text="实际发布时间")
    publication_lag_days = models.IntegerField(default=0, help_text="发布延迟天数")
    source = models.CharField(max_length=20, help_text="数据源")
    revision_number = models.IntegerField(default=1, help_text="修订版本号")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'macro_indicator'
        unique_together = [['code', 'reporting_period', 'revision_number']]
        ordering = ['-reporting_period', '-revision_number']
        indexes = [
            models.Index(fields=['code', '-reporting_period']),
            models.Index(fields=['period_type']),
        ]

    def __str__(self):
        period_label = self.get_period_type_display()
        return f"{self.code}@{self.reporting_date}({period_label})={self.value}"

    def get_period_type_display(self):
        """获取期间类型的显示文本"""
        # 先查标准类型
        standard_types = dict(self.PERIOD_TYPE_CHOICES)
        if self.period_type in standard_types:
            return standard_types[self.period_type]
        # 再查扩展类型
        if self.period_type in self.EXTENDED_PERIOD_TYPES:
            return self.EXTENDED_PERIOD_TYPES[self.period_type]
        # 返回原始值
        return self.period_type

    @property
    def reporting_date(self):
        """获取报告日期（用于兼容旧代码）"""
        return self.reporting_period

    @property
    def observed_at(self):
        """兼容旧 API：observed_at 别名"""
        return self.reporting_period

    @property
    def is_point_data(self):
        """是否为标准时点数据（日度）"""
        return self.period_type == 'D'

    @property
    def is_period_data(self):
        """是否为期间数据（非日度）"""
        return self.period_type != 'D'

    @property
    def is_term_data(self):
        """是否为期限类数据（如 3M、10Y 等利率）"""
        # 检查是否以 M 或 Y 结尾，但不是标准的 M 或 Y
        if len(self.period_type) > 1:
            return (self.period_type.endswith('M') and self.period_type != 'M') or \
                   (self.period_type.endswith('Y') and self.period_type != 'Y')
        return False


class ExchangeRateModel(models.Model):
    """
    汇率记录表

    存储货币对的历史汇率，支持按日期查询。
    数据来源：AKShare fx_spot_quote() 或手动录入。
    """

    from_currency = models.CharField(max_length=10, verbose_name="源货币")
    to_currency = models.CharField(max_length=10, verbose_name="目标货币")
    rate = models.DecimalField(
        max_digits=16, decimal_places=6, verbose_name="汇率"
    )
    effective_date = models.DateField(verbose_name="生效日期", db_index=True)
    source = models.CharField(
        max_length=30, default="akshare", verbose_name="数据来源"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "macro_exchange_rate"
        verbose_name = "汇率记录"
        verbose_name_plural = "汇率记录"
        ordering = ["-effective_date"]
        unique_together = [("from_currency", "to_currency", "effective_date")]
        indexes = [
            models.Index(
                fields=["from_currency", "to_currency", "-effective_date"],
                name="exchange_rate_lookup_idx",
            ),
        ]

    def __str__(self):
        return f"{self.from_currency}/{self.to_currency} = {self.rate} ({self.effective_date})"

# Shared configuration models repatriated from shared.infrastructure.models

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

