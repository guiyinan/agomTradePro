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
