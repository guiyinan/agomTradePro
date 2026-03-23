"""
板块分析模块 - ORM 模型定义

遵循项目架构约束：
- 使用 Django ORM 定义数据表结构
- 包含板块基本信息、板块指数、板块成分股等表
"""

from decimal import Decimal

from django.db import models


class SectorInfoModel(models.Model):
    """板块基本信息表

    存储申万行业分类信息（一级、二级、三级）
    """

    sector_code = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        verbose_name="板块代码"
    )
    sector_name = models.CharField(
        max_length=50,
        verbose_name="板块名称"
    )
    level = models.CharField(
        max_length=10,
        choices=[
            ('SW1', '申万一级'),
            ('SW2', '申万二级'),
            ('SW3', '申万三级'),
        ],
        db_index=True,
        verbose_name="板块级别"
    )
    parent_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name="父级板块代码"
    )

    # 元数据
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否活跃"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sector_info'
        verbose_name = '板块基本信息'
        verbose_name_plural = '板块基本信息'
        indexes = [
            models.Index(fields=['sector_code']),
            models.Index(fields=['level']),
            models.Index(fields=['parent_code']),
        ]
        ordering = ['level', 'sector_code']

    def __str__(self):
        return f"{self.sector_code} - {self.sector_name} ({self.get_level_display()})"


class SectorIndexModel(models.Model):
    """板块指数日线数据表

    存储申万行业指数的日线行情数据
    """

    sector_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="板块代码"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )

    # 价格数据
    open_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="开盘点位"
    )
    high = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="最高点位"
    )
    low = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="最低点位"
    )
    close = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="收盘点位"
    )

    # 成交数据
    volume = models.BigIntegerField(
        verbose_name="成交量（手）"
    )
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

    # 涨跌幅
    change_pct = models.FloatField(
        verbose_name="涨跌幅（%）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sector_index_daily'
        verbose_name = '板块指数日线'
        verbose_name_plural = '板块指数日线'
        unique_together = [['sector_code', 'trade_date']]
        indexes = [
            models.Index(fields=['sector_code', 'trade_date']),
            models.Index(fields=['trade_date']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.sector_code} - {self.trade_date}"


class SectorConstituentModel(models.Model):
    """板块成分股关系表

    存储板块与股票的从属关系
    """

    sector_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="板块代码"
    )
    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    enter_date = models.DateField(
        verbose_name="纳入日期"
    )
    exit_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="剔除日期"
    )

    # 元数据
    is_current = models.BooleanField(
        default=True,
        verbose_name="是否当前成分股"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sector_constituent'
        verbose_name = '板块成分股'
        verbose_name_plural = '板块成分股'
        indexes = [
            models.Index(fields=['sector_code', 'is_current']),
            models.Index(fields=['stock_code', 'is_current']),
        ]
        ordering = ['sector_code', '-enter_date']

    def __str__(self):
        return f"{self.sector_code} - {self.stock_code}"


class SectorRelativeStrengthModel(models.Model):
    """板块相对强弱指标表

    存储板块相对于大盘的相对强弱指标
    """

    sector_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="板块代码"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )

    # 相对强弱指标
    relative_strength = models.FloatField(
        verbose_name="相对强弱（板块收益率 - 大盘收益率）"
    )
    momentum = models.FloatField(
        verbose_name="动量（N日累计收益率，%）"
    )
    momentum_window = models.IntegerField(
        default=20,
        verbose_name="动量计算窗口"
    )
    beta = models.FloatField(
        null=True,
        blank=True,
        verbose_name="贝塔系数"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sector_relative_strength'
        verbose_name = '板块相对强弱'
        verbose_name_plural = '板块相对强弱'
        unique_together = [['sector_code', 'trade_date']]
        indexes = [
            models.Index(fields=['sector_code', '-trade_date']),
            models.Index(fields=['trade_date']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.sector_code} - {self.trade_date}"
