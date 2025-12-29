"""
ORM Models for Macro Data.

Django models for persisting macro indicator data and data source configurations.
"""

from django.db import models


class DataSourceConfig(models.Model):
    """数据源配置 ORM 模型"""

    SOURCE_TYPE_CHOICES = [
        ('tushare', 'Tushare Pro'),
        ('akshare', 'AKShare'),
        ('fred', 'FRED'),
        ('wind', 'Wind'),
        ('choice', 'Choice'),
    ]

    name = models.CharField(max_length=50, unique=True, help_text="数据源名称")
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        help_text="数据源类型"
    )
    is_active = models.BooleanField(default=True, help_text="是否启用")
    priority = models.IntegerField(default=0, help_text="优先级（数字越小越优先）")
    api_endpoint = models.URLField(blank=True, help_text="API 端点 URL")
    api_key = models.CharField(max_length=200, blank=True, help_text="API 密钥")
    api_secret = models.CharField(max_length=200, blank=True, help_text="API 密钥（如需要）")
    extra_config = models.JSONField(default=dict, blank=True, help_text="额外配置参数")
    description = models.TextField(blank=True, help_text="描述")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'data_source_config'
        ordering = ['priority', 'name']
        verbose_name = "数据源配置"
        verbose_name_plural = "数据源配置"

    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"


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
    value = models.DecimalField(max_digits=20, decimal_places=6, help_text="指标值")

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
