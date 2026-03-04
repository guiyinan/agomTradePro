"""
个股分析模块 Infrastructure 层 ORM 模型

遵循四层架构规范：
- Infrastructure 层允许导入 django.db
- 实现数据持久化逻辑
"""

from django.db import models
from decimal import Decimal


class StockInfoModel(models.Model):
    """个股基本信息表"""

    stock_code = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        verbose_name="股票代码"
    )
    name = models.CharField(max_length=100, verbose_name="股票名称")
    sector = models.CharField(max_length=50, verbose_name="所属行业")
    market = models.CharField(
        max_length=10,
        choices=[
            ('SH', '上交所'),
            ('SZ', '深交所'),
            ('BJ', '北交所')
        ],
        verbose_name="交易市场"
    )
    list_date = models.DateField(verbose_name="上市日期")

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否活跃")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'equity_stock_info'
        verbose_name = '个股基本信息'
        verbose_name_plural = '个股基本信息'
        indexes = [
            models.Index(fields=['stock_code']),
            models.Index(fields=['sector']),
        ]

    def __str__(self):
        return f"{self.stock_code} - {self.name}"


class StockDailyModel(models.Model):
    """个股日线数据表"""

    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )

    # 价格数据
    open = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="开盘价"
    )
    high = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="最高价"
    )
    low = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="最低价"
    )
    close = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="收盘价"
    )

    # 成交数据
    volume = models.BigIntegerField(verbose_name="成交量（手）")
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="成交额（元）"
    )
    turnover_rate = models.FloatField(
        null=True,
        blank=True,
        verbose_name="换手率（%）"
    )

    # 复权因子
    adj_factor = models.FloatField(
        default=1.0,
        verbose_name="复权因子"
    )

    # 技术指标
    ma5 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="5日均线"
    )
    ma20 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="20日均线"
    )
    ma60 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="60日均线"
    )

    # MACD
    macd = models.FloatField(
        null=True,
        blank=True,
        verbose_name="MACD"
    )
    macd_signal = models.FloatField(
        null=True,
        blank=True,
        verbose_name="MACD 信号线"
    )
    macd_hist = models.FloatField(
        null=True,
        blank=True,
        verbose_name="MACD 柱状图"
    )

    # RSI
    rsi = models.FloatField(
        null=True,
        blank=True,
        verbose_name="RSI（14日）"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'equity_stock_daily'
        verbose_name = '个股日线数据'
        verbose_name_plural = '个股日线数据'
        unique_together = [['stock_code', 'trade_date']]
        indexes = [
            models.Index(fields=['stock_code', 'trade_date']),
            models.Index(fields=['trade_date']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.stock_code} - {self.trade_date}"


class FinancialDataModel(models.Model):
    """财务数据表"""

    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    report_date = models.DateField(
        db_index=True,
        verbose_name="报告期"
    )
    report_type = models.CharField(
        max_length=10,
        choices=[
            ('1Q', '一季报'),
            ('2Q', '中报'),
            ('3Q', '三季报'),
            ('4Q', '年报')
        ],
        verbose_name="报告类型"
    )

    # 利润表（单位：元）
    revenue = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="营业收入"
    )
    net_profit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="净利润"
    )

    # 增长率（%）
    revenue_growth = models.FloatField(
        null=True,
        blank=True,
        verbose_name="营收增长率"
    )
    net_profit_growth = models.FloatField(
        null=True,
        blank=True,
        verbose_name="净利润增长率"
    )

    # 资产负债表（单位：元）
    total_assets = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="总资产"
    )
    total_liabilities = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="总负债"
    )
    equity = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="股东权益"
    )

    # 财务指标（%）
    roe = models.FloatField(verbose_name="净资产收益率")
    roa = models.FloatField(
        null=True,
        blank=True,
        verbose_name="总资产收益率"
    )
    debt_ratio = models.FloatField(verbose_name="资产负债率")

    # 元数据
    publish_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="发布日期"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'equity_financial_data'
        verbose_name = '财务数据'
        verbose_name_plural = '财务数据'
        unique_together = [['stock_code', 'report_date', 'report_type']]
        indexes = [
            models.Index(fields=['stock_code', 'report_date']),
            models.Index(fields=['report_date']),
        ]
        ordering = ['-report_date']

    def __str__(self):
        return f"{self.stock_code} - {self.report_date}"


class ValuationModel(models.Model):
    """估值指标表"""

    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )

    # 估值指标
    pe = models.FloatField(
        null=True,
        blank=True,
        verbose_name="市盈率（动态）"
    )
    pe_ttm = models.FloatField(
        null=True,
        blank=True,
        verbose_name="市盈率（TTM）"
    )
    pb = models.FloatField(
        null=True,
        blank=True,
        verbose_name="市净率"
    )
    ps = models.FloatField(
        null=True,
        blank=True,
        verbose_name="市销率"
    )

    # 市值（单位：元）
    total_mv = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="总市值（元）"
    )
    circ_mv = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        verbose_name="流通市值（元）"
    )

    # 其他指标
    dividend_yield = models.FloatField(
        null=True,
        blank=True,
        verbose_name="股息率（%）"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'equity_valuation'
        verbose_name = '估值指标'
        verbose_name_plural = '估值指标'
        unique_together = [['stock_code', 'trade_date']]
        indexes = [
            models.Index(fields=['stock_code', 'trade_date']),
            models.Index(fields=['trade_date']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.stock_code} - {self.trade_date}"


class ScoringWeightConfigModel(models.Model):
    """股票筛选评分权重配置表

    存储股票筛选时各评分维度的权重分配，支持通过 Django Admin 动态调整。
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="配置名称"
    )
    description = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="配置描述"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    # 评分维度权重（总和应为 1.0）
    growth_weight = models.FloatField(
        default=0.4,
        verbose_name="成长性评分权重"
    )
    profitability_weight = models.FloatField(
        default=0.4,
        verbose_name="盈利能力评分权重"
    )
    valuation_weight = models.FloatField(
        default=0.2,
        verbose_name="估值评分权重"
    )

    # 成长性内部权重（总和应为 1.0）
    revenue_growth_weight = models.FloatField(
        default=0.5,
        verbose_name="营收增长率权重"
    )
    profit_growth_weight = models.FloatField(
        default=0.5,
        verbose_name="净利润增长率权重"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'equity_scoring_weight_config'
        verbose_name = '股票评分权重配置'
        verbose_name_plural = '股票评分权重配置'
        ordering = ['-is_active', '-created_at']

    def __str__(self):
        return f"{self.name} ({'启用' if self.is_active else '未启用'})"

    def clean(self):
        """验证权重配置"""
        from django.core.exceptions import ValidationError

        # 检查维度权重总和
        total_dimension = (
            self.growth_weight +
            self.profitability_weight +
            self.valuation_weight
        )
        if abs(total_dimension - 1.0) > 0.01:
            raise ValidationError({
                'growth_weight': f'评分维度权重总和必须为 1.0，当前为 {total_dimension:.2f}'
            })

        # 检查成长性内部权重总和
        total_growth = (
            self.revenue_growth_weight +
            self.profit_growth_weight
        )
        if abs(total_growth - 1.0) > 0.01:
            raise ValidationError({
                'revenue_growth_weight': f'成长性内部权重总和必须为 1.0，当前为 {total_growth:.2f}'
            })

        # 检查权重范围
        for field_name in ['growth_weight', 'profitability_weight', 'valuation_weight',
                           'revenue_growth_weight', 'profit_growth_weight']:
            value = getattr(self, field_name)
            if not (0.0 <= value <= 1.0):
                raise ValidationError({
                    field_name: f'权重必须在 [0.0, 1.0] 范围内，当前为 {value}'
                })

    def save(self, *args, **kwargs):
        """保存前进行验证"""
        self.full_clean()
        super().save(*args, **kwargs)

    def to_domain_entity(self):
        """转换为 Domain 层实体"""
        from apps.equity.domain.entities import ScoringWeightConfig

        return ScoringWeightConfig(
            name=self.name,
            description=self.description or "",
            is_active=self.is_active,
            growth_weight=self.growth_weight,
            profitability_weight=self.profitability_weight,
            valuation_weight=self.valuation_weight,
            revenue_growth_weight=self.revenue_growth_weight,
            profit_growth_weight=self.profit_growth_weight
        )


class StockPoolSnapshot(models.Model):
    """股票池快照表

    存储筛选后的股票池快照，支持历史追踪。
    """

    stock_codes = models.JSONField(
        default=list,
        verbose_name="股票代码列表"
    )
    regime = models.CharField(
        max_length=20,
        verbose_name="筛选时使用的 Regime"
    )
    as_of_date = models.DateField(
        verbose_name="数据截止日期"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否为当前活跃池"
    )

    # 统计信息（冗余存储，便于查询）
    count = models.IntegerField(
        default=0,
        verbose_name="股票数量"
    )
    avg_roe = models.FloatField(
        null=True,
        blank=True,
        verbose_name="平均 ROE"
    )
    avg_pe = models.FloatField(
        null=True,
        blank=True,
        verbose_name="平均 PE"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = 'equity_stock_pool_snapshot'
        verbose_name = '股票池快照'
        verbose_name_plural = '股票池快照'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"股票池 {self.regime} - {self.as_of_date} ({self.count} 只)"
