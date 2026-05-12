"""
Factor Module Infrastructure Layer - ORM Models

Django ORM models for factor stock selection system.
Follows four-layer architecture.
"""


from django.db import models


class FactorDefinitionModel(models.Model):
    """Factor definition table"""

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="因子代码"
    )
    name = models.CharField(
        max_length=100,
        verbose_name="因子名称"
    )
    category = models.CharField(
        max_length=20,
        choices=[
            ('value', '价值'),
            ('quality', '质量'),
            ('growth', '成长'),
            ('momentum', '动量'),
            ('volatility', '波动'),
            ('liquidity', '流动性'),
            ('technical', '技术'),
        ],
        verbose_name="因子类别"
    )
    description = models.TextField(
        blank=True,
        verbose_name="因子描述"
    )
    data_source = models.CharField(
        max_length=50,
        verbose_name="数据来源"
    )
    data_field = models.CharField(
        max_length=100,
        verbose_name="数据字段"
    )
    direction = models.CharField(
        max_length=20,
        choices=[
            ('positive', '正向'),
            ('negative', '反向'),
            ('neutral', '中性'),
        ],
        default='positive',
        verbose_name="因子方向"
    )
    update_frequency = models.CharField(
        max_length=20,
        default='daily',
        verbose_name="更新频率"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    # Data quality requirements
    min_data_points = models.IntegerField(
        default=20,
        verbose_name="最小数据点"
    )
    allow_missing = models.BooleanField(
        default=False,
        verbose_name="允许缺失"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'factor_definition'
        verbose_name = '因子定义'
        verbose_name_plural = '因子定义'
        ordering = ['category', 'code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.factor.domain.entities import FactorCategory, FactorDefinition, FactorDirection

        direction_map = {
            'positive': FactorDirection.POSITIVE,
            'negative': FactorDirection.NEGATIVE,
            'neutral': FactorDirection.NEUTRAL,
        }

        return FactorDefinition(
            code=self.code,
            name=self.name,
            category=FactorCategory(self.category),
            description=self.description or "",
            data_source=self.data_source,
            data_field=self.data_field,
            direction=direction_map[self.direction],
            update_frequency=self.update_frequency,
            is_active=self.is_active,
            min_data_points=self.min_data_points,
            allow_missing=self.allow_missing,
        )


class FactorExposureModel(models.Model):
    """Factor exposure table"""

    stock_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="股票代码"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )
    factor_code = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="因子代码"
    )
    factor_value = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        verbose_name="因子值"
    )
    percentile_rank = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="百分位排名"
    )
    z_score = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        verbose_name="Z得分"
    )
    normalized_score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.0,
        verbose_name="标准化得分"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'factor_exposure'
        verbose_name = '因子暴露度'
        verbose_name_plural = '因子暴露度'
        unique_together = [('stock_code', 'trade_date', 'factor_code')]
        indexes = [
            models.Index(fields=['trade_date', 'factor_code']),
            models.Index(fields=['stock_code', 'trade_date']),
        ]
        ordering = ['-trade_date', '-percentile_rank']

    def __str__(self):
        return f"{self.stock_code} - {self.factor_code} - {self.trade_date}"


class FactorPortfolioConfigModel(models.Model):
    """Factor portfolio configuration table"""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="配置名称"
    )
    description = models.TextField(
        blank=True,
        verbose_name="配置描述"
    )
    factor_weights = models.JSONField(
        default=dict,
        verbose_name="因子权重"
    )
    universe = models.CharField(
        max_length=20,
        default='all_a',
        verbose_name="股票池"
    )
    min_market_cap = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="最小市值（亿）"
    )
    max_market_cap = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="最大市值（亿）"
    )
    max_pe = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="最大PE"
    )
    min_pe = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="最小PE"
    )
    max_pb = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="最大PB"
    )
    max_debt_ratio = models.FloatField(
        null=True,
        blank=True,
        verbose_name="最大资产负债率（%）"
    )
    top_n = models.IntegerField(
        default=30,
        verbose_name="选股数量"
    )
    rebalance_frequency = models.CharField(
        max_length=20,
        default='monthly',
        verbose_name="调仓频率"
    )
    weight_method = models.CharField(
        max_length=50,
        default='equal_weight',
        verbose_name="权重方式"
    )
    max_sector_weight = models.FloatField(
        default=0.4,
        verbose_name="最大行业权重"
    )
    max_single_stock_weight = models.FloatField(
        default=0.05,
        verbose_name="最大单股权重"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'factor_portfolio_config'
        verbose_name = '因子组合配置'
        verbose_name_plural = '因子组合配置'
        ordering = ['-is_active', '-created_at']

    def __str__(self):
        return f"{self.name} ({'启用' if self.is_active else '未启用'})"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.factor.domain.entities import FactorPortfolioConfig

        return FactorPortfolioConfig(
            name=self.name,
            description=self.description or "",
            factor_weights=self.factor_weights,
            universe=self.universe,
            min_market_cap=float(self.min_market_cap) if self.min_market_cap else None,
            max_market_cap=float(self.max_market_cap) if self.max_market_cap else None,
            max_pe=float(self.max_pe) if self.max_pe else None,
            min_pe=float(self.min_pe) if self.min_pe else None,
            max_pb=float(self.max_pb) if self.max_pb else None,
            max_debt_ratio=self.max_debt_ratio,
            top_n=self.top_n,
            rebalance_frequency=self.rebalance_frequency,
            weight_method=self.weight_method,
            max_sector_weight=self.max_sector_weight,
            max_single_stock_weight=self.max_single_stock_weight,
            is_active=self.is_active,
        )


class FactorPortfolioHoldingModel(models.Model):
    """Factor portfolio holdings table"""

    config = models.ForeignKey(
        FactorPortfolioConfigModel,
        on_delete=models.CASCADE,
        related_name='holdings',
        verbose_name="配置"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )
    stock_code = models.CharField(
        max_length=20,
        verbose_name="股票代码"
    )
    stock_name = models.CharField(
        max_length=100,
        verbose_name="股票名称"
    )
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        verbose_name="权重"
    )
    factor_score = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="因子得分"
    )
    rank = models.IntegerField(
        verbose_name="排名"
    )
    sector = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="行业"
    )
    factor_scores = models.JSONField(
        default=dict,
        verbose_name="因子得分明细"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'factor_portfolio_holdings'
        verbose_name = '因子组合持仓'
        verbose_name_plural = '因子组合持仓'
        unique_together = [('config', 'trade_date', 'stock_code')]
        indexes = [
            models.Index(fields=['config', 'trade_date']),
            models.Index(fields=['trade_date', 'rank']),
        ]
        ordering = ['-trade_date', 'rank']

    def __str__(self):
        return f"{self.config.name} - {self.stock_code} - {self.trade_date}"


class FactorPerformanceModel(models.Model):
    """Factor performance tracking table"""

    factor_code = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="因子代码"
    )
    period_start = models.DateField(
        verbose_name="期间开始"
    )
    period_end = models.DateField(
        verbose_name="期间结束"
    )

    # Return metrics
    total_return = models.FloatField(
        verbose_name="总收益率"
    )
    annual_return = models.FloatField(
        verbose_name="年化收益率"
    )
    sharpe_ratio = models.FloatField(
        verbose_name="夏普比率"
    )
    max_drawdown = models.FloatField(
        verbose_name="最大回撤"
    )

    # Selection metrics
    win_rate = models.FloatField(
        verbose_name="胜率"
    )
    avg_rank = models.FloatField(
        verbose_name="平均排名"
    )

    # Turnover
    turnover_rate = models.FloatField(
        default=0.0,
        verbose_name="换手率"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'factor_performance'
        verbose_name = '因子表现'
        verbose_name_plural = '因子表现'
        unique_together = [('factor_code', 'period_start', 'period_end')]
        ordering = ['-period_start', 'factor_code']

    def __str__(self):
        return f"{self.factor_code} - {self.period_start} to {self.period_end}"
