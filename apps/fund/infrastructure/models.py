"""
基金分析模块 - ORM 模型定义

遵循项目架构约束：
- 使用 Django ORM 定义数据表结构
- 包含基金基本信息、净值、持仓、业绩等表
"""

from decimal import Decimal

from django.db import models


class FundInfoModel(models.Model):
    """基金基本信息表

    存公募基金的基本信息
    """

    fund_code = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        verbose_name="基金代码"
    )
    fund_name = models.CharField(
        max_length=100,
        verbose_name="基金名称"
    )
    fund_type = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="基金类型",
        help_text="股票型/债券型/混合型/指数型/货币型/QDII/商品型"
    )
    investment_style = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="投资风格",
        help_text="成长/价值/平衡/商品/稳健"
    )
    setup_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="成立日期"
    )
    management_company = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="管理人"
    )
    custodian = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="托管人"
    )
    fund_scale = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="基金规模（元）"
    )

    # 元数据
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否活跃"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fund_info'
        verbose_name = '基金基本信息'
        verbose_name_plural = '基金基本信息'
        indexes = [
            models.Index(fields=['fund_code']),
            models.Index(fields=['fund_type', 'is_active']),
            models.Index(fields=['investment_style']),
        ]
        ordering = ['fund_code']

    def __str__(self):
        return f"{self.fund_code} - {self.fund_name}"


class FundManagerModel(models.Model):
    """基金经理表

    存储基金经理的任职信息
    """

    fund_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="基金代码"
    )
    manager_name = models.CharField(
        max_length=50,
        verbose_name="经理姓名"
    )
    tenure_start = models.DateField(
        verbose_name="任职开始日期"
    )
    tenure_end = models.DateField(
        null=True,
        blank=True,
        verbose_name="任职结束日期"
    )
    total_tenure_days = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="任期天数"
    )
    fund_return = models.FloatField(
        null=True,
        blank=True,
        verbose_name="任期期间基金收益率（%）"
    )

    # 元数据
    is_current = models.BooleanField(
        default=True,
        verbose_name="是否在任"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fund_manager'
        verbose_name = '基金经理'
        verbose_name_plural = '基金经理'
        indexes = [
            models.Index(fields=['fund_code', 'is_current']),
            models.Index(fields=['manager_name']),
        ]
        ordering = ['fund_code', '-tenure_start']

    def __str__(self):
        return f"{self.fund_code} - {self.manager_name}"


class FundNetValueModel(models.Model):
    """基金净值数据表

    存储基金的日净值数据
    """

    fund_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="基金代码"
    )
    nav_date = models.DateField(
        db_index=True,
        verbose_name="净值日期"
    )
    unit_nav = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="单位净值"
    )
    accum_nav = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="累计净值"
    )
    daily_return = models.FloatField(
        null=True,
        blank=True,
        verbose_name="日收益率（%）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fund_net_value'
        verbose_name = '基金净值'
        verbose_name_plural = '基金净值'
        unique_together = [['fund_code', 'nav_date']]
        indexes = [
            models.Index(fields=['fund_code', '-nav_date']),
            models.Index(fields=['nav_date']),
        ]
        ordering = ['-nav_date']

    def __str__(self):
        return f"{self.fund_code} - {self.nav_date}"


class FundHoldingModel(models.Model):
    """基金持仓表

    存储基金持仓股票信息
    """

    fund_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="基金代码"
    )
    report_date = models.DateField(
        db_index=True,
        verbose_name="报告期"
    )
    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    stock_name = models.CharField(
        max_length=100,
        verbose_name="股票名称"
    )
    holding_amount = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="持有数量（股）"
    )
    holding_value = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="持有市值（元）"
    )
    holding_ratio = models.FloatField(
        null=True,
        blank=True,
        verbose_name="占净值比例（%）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fund_holding'
        verbose_name = '基金持仓'
        verbose_name_plural = '基金持仓'
        unique_together = [['fund_code', 'report_date', 'stock_code']]
        indexes = [
            models.Index(fields=['fund_code', '-report_date']),
            models.Index(fields=['stock_code', '-report_date']),
        ]
        ordering = ['-report_date', '-holding_ratio']

    def __str__(self):
        return f"{self.fund_code} - {self.stock_code} - {self.report_date}"


class FundSectorAllocationModel(models.Model):
    """基金行业配置表

    存储基金的行业配置比例
    """

    fund_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="基金代码"
    )
    report_date = models.DateField(
        db_index=True,
        verbose_name="报告期"
    )
    sector_name = models.CharField(
        max_length=50,
        verbose_name="行业名称"
    )
    allocation_ratio = models.FloatField(
        verbose_name="配置比例（%）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fund_sector_allocation'
        verbose_name = '基金行业配置'
        verbose_name_plural = '基金行业配置'
        unique_together = [['fund_code', 'report_date', 'sector_name']]
        indexes = [
            models.Index(fields=['fund_code', '-report_date']),
            models.Index(fields=['report_date']),
        ]
        ordering = ['-report_date', '-allocation_ratio']

    def __str__(self):
        return f"{self.fund_code} - {self.sector_name} - {self.report_date}"


class FundPerformanceModel(models.Model):
    """基金业绩指标表

    存储基金的历史业绩指标
    """

    fund_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="基金代码"
    )
    start_date = models.DateField(
        verbose_name="计算起始日期"
    )
    end_date = models.DateField(
        db_index=True,
        verbose_name="计算结束日期"
    )

    # 收益指标
    total_return = models.FloatField(
        verbose_name="区间收益率（%）"
    )
    annualized_return = models.FloatField(
        null=True,
        blank=True,
        verbose_name="年化收益率（%）"
    )

    # 风险指标
    volatility = models.FloatField(
        null=True,
        blank=True,
        verbose_name="波动率（%）"
    )
    max_drawdown = models.FloatField(
        null=True,
        blank=True,
        verbose_name="最大回撤（%）"
    )

    # 风险调整收益指标
    sharpe_ratio = models.FloatField(
        null=True,
        blank=True,
        verbose_name="夏普比率"
    )
    beta = models.FloatField(
        null=True,
        blank=True,
        verbose_name="贝塔系数"
    )
    alpha = models.FloatField(
        null=True,
        blank=True,
        verbose_name="阿尔法（%）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fund_performance'
        verbose_name = '基金业绩指标'
        verbose_name_plural = '基金业绩指标'
        unique_together = [['fund_code', 'start_date', 'end_date']]
        indexes = [
            models.Index(fields=['fund_code', '-end_date']),
            models.Index(fields=['end_date']),
        ]
        ordering = ['-end_date']

    def __str__(self):
        return f"{self.fund_code} - {self.start_date} ~ {self.end_date}"
