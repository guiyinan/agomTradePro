"""
Rotation Module Infrastructure Layer - ORM Models

Django ORM models for asset rotation system.
Follows four-layer architecture.
"""

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from decimal import Decimal


class AssetClassModel(models.Model):
    """Asset class table"""

    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name="资产代码"
    )
    name = models.CharField(
        max_length=100,
        verbose_name="资产名称"
    )
    category = models.CharField(
        max_length=20,
        choices=[
            ('equity', '股票'),
            ('bond', '债券'),
            ('commodity', '商品'),
            ('currency', '货币'),
            ('alternative', '另类'),
        ],
        verbose_name="资产类别"
    )
    description = models.TextField(
        blank=True,
        verbose_name="资产描述"
    )
    underlying_index = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="标的指数"
    )
    currency = models.CharField(
        max_length=10,
        default='CNY',
        verbose_name="计价货币"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rotation_asset_class'
        verbose_name = '资产类别'
        verbose_name_plural = '资产类别'
        ordering = ['category', 'code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.rotation.domain.entities import AssetClass, AssetCategory

        return AssetClass(
            code=self.code,
            name=self.name,
            category=AssetCategory(self.category),
            description=self.description or "",
            underlying_index=self.underlying_index or None,
            currency=self.currency,
            is_active=self.is_active,
        )


class RotationConfigModel(models.Model):
    """Rotation configuration table"""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="配置名称"
    )
    description = models.TextField(
        blank=True,
        verbose_name="配置描述"
    )
    strategy_type = models.CharField(
        max_length=50,
        choices=[
            ('regime_based', '基于象限'),
            ('momentum', '动量轮动'),
            ('risk_parity', '风险平价'),
            ('mean_reversion', '均值回归'),
            ('custom', '自定义'),
        ],
        default='momentum',
        verbose_name="策略类型"
    )
    asset_universe = models.JSONField(
        default=list,
        verbose_name="资产池"
    )
    params = models.JSONField(
        default=dict,
        verbose_name="策略参数"
    )
    rebalance_frequency = models.CharField(
        max_length=20,
        default='monthly',
        verbose_name="调仓频率"
    )
    min_weight = models.FloatField(
        default=0.0,
        verbose_name="最小权重"
    )
    max_weight = models.FloatField(
        default=1.0,
        verbose_name="最大权重"
    )
    max_turnover = models.FloatField(
        default=1.0,
        verbose_name="最大换手率"
    )
    lookback_period = models.IntegerField(
        default=252,
        verbose_name="回溯周期（天）"
    )
    regime_allocations = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="象限配置"
    )
    momentum_periods = models.JSONField(
        default=list,
        verbose_name="动量周期"
    )
    top_n = models.IntegerField(
        default=3,
        verbose_name="选资产数量"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rotation_config'
        verbose_name = '轮动配置'
        verbose_name_plural = '轮动配置'
        ordering = ['-is_active', '-created_at']

    def __str__(self):
        return f"{self.name} ({'启用' if self.is_active else '未启用'})"

    def to_domain(self):
        """Convert to domain entity"""
        from apps.rotation.domain.entities import RotationConfig, RotationStrategyType

        strategy_map = {
            'regime_based': RotationStrategyType.REGIME_BASED,
            'momentum': RotationStrategyType.MOMENTUM,
            'risk_parity': RotationStrategyType.RISK_PARITY,
            'mean_reversion': RotationStrategyType.MEAN_REVERSION,
            'custom': RotationStrategyType.CUSTOM,
        }

        return RotationConfig(
            name=self.name,
            description=self.description or "",
            strategy_type=strategy_map.get(self.strategy_type, RotationStrategyType.MOMENTUM),
            asset_universe=self.asset_universe,
            params=self.params,
            rebalance_frequency=self.rebalance_frequency,
            min_weight=self.min_weight,
            max_weight=self.max_weight,
            max_turnover=self.max_turnover,
            lookback_period=self.lookback_period,
            regime_allocations=self.regime_allocations,
            is_active=self.is_active,
            top_n=self.top_n,
        )


class RotationSignalModel(models.Model):
    """Rotation signal history table"""

    config = models.ForeignKey(
        RotationConfigModel,
        on_delete=models.CASCADE,
        related_name='signals',
        verbose_name="配置"
    )
    signal_date = models.DateField(
        db_index=True,
        verbose_name="信号日期"
    )
    target_allocation = models.JSONField(
        verbose_name="目标配置"
    )
    current_regime = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="当前象限"
    )
    momentum_ranking = models.JSONField(
        default=list,
        blank=True,
        verbose_name="动量排名"
    )
    expected_volatility = models.FloatField(
        default=0.0,
        verbose_name="预期波动率"
    )
    expected_return = models.FloatField(
        default=0.0,
        verbose_name="预期收益"
    )
    action_required = models.CharField(
        max_length=50,
        default='hold',
        verbose_name="建议操作"
    )
    reason = models.TextField(
        blank=True,
        verbose_name="原因说明"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rotation_signal'
        verbose_name = '轮动信号'
        verbose_name_plural = '轮动信号'
        unique_together = [('config', 'signal_date')]
        indexes = [
            models.Index(fields=['signal_date']),
            models.Index(fields=['config', 'signal_date']),
        ]
        ordering = ['-signal_date']

    def __str__(self):
        return f"{self.config.name} - {self.signal_date}"


class RotationPortfolioModel(models.Model):
    """Rotation portfolio state table"""

    config = models.ForeignKey(
        RotationConfigModel,
        on_delete=models.CASCADE,
        related_name='portfolios',
        verbose_name="配置"
    )
    trade_date = models.DateField(
        db_index=True,
        verbose_name="交易日期"
    )
    current_allocation = models.JSONField(
        verbose_name="当前配置"
    )
    daily_return = models.FloatField(
        default=0.0,
        verbose_name="日收益率"
    )
    cumulative_return = models.FloatField(
        default=0.0,
        verbose_name="累计收益率"
    )
    portfolio_volatility = models.FloatField(
        default=0.0,
        verbose_name="组合波动率"
    )
    max_drawdown = models.FloatField(
        default=0.0,
        verbose_name="最大回撤"
    )
    turnover_since_last = models.FloatField(
        default=0.0,
        verbose_name="换手率"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rotation_portfolio'
        verbose_name = '轮动组合'
        verbose_name_plural = '轮动组合'
        unique_together = [('config', 'trade_date')]
        indexes = [
            models.Index(fields=['config', 'trade_date']),
        ]
        ordering = ['-trade_date']

    def __str__(self):
        return f"{self.config.name} - {self.trade_date}"


class MomentumScoreModel(models.Model):
    """Momentum score cache table"""

    asset_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产代码"
    )
    calc_date = models.DateField(
        db_index=True,
        verbose_name="计算日期"
    )
    momentum_1m = models.FloatField(
        default=0.0,
        verbose_name="1月动量"
    )
    momentum_3m = models.FloatField(
        default=0.0,
        verbose_name="3月动量"
    )
    momentum_6m = models.FloatField(
        default=0.0,
        verbose_name="6月动量"
    )
    momentum_12m = models.FloatField(
        default=0.0,
        verbose_name="12月动量"
    )
    composite_score = models.FloatField(
        default=0.0,
        verbose_name="综合得分"
    )
    rank = models.IntegerField(
        default=0,
        verbose_name="排名"
    )
    sharpe_1m = models.FloatField(
        default=0.0,
        verbose_name="1月夏普"
    )
    sharpe_3m = models.FloatField(
        default=0.0,
        verbose_name="3月夏普"
    )
    ma_signal = models.CharField(
        max_length=20,
        default='neutral',
        verbose_name="均线信号"
    )
    trend_strength = models.FloatField(
        default=0.0,
        verbose_name="趋势强度"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rotation_momentum_score'
        verbose_name = '动量得分'
        verbose_name_plural = '动量得分'
        unique_together = [('asset_code', 'calc_date')]
        indexes = [
            models.Index(fields=['calc_date', 'rank']),
            models.Index(fields=['calc_date', 'composite_score']),
        ]
        ordering = ['-calc_date', '-composite_score']

    def __str__(self):
        return f"{self.asset_code} - {self.calc_date}"


class RotationTemplateModel(models.Model):
    """
    预设风险模板表

    保守/稳健/激进三种模板的象限配置，存储在数据库。
    通过 init_rotation 管理命令初始化，禁止在代码中硬编码权重数据。
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="模板名称"
    )
    key = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="模板标识",
        help_text="conservative / moderate / aggressive"
    )
    description = models.TextField(blank=True, verbose_name="模板描述")

    # 格式：{regime_name: {asset_code: weight(0.0-1.0)}}
    regime_allocations = models.JSONField(
        default=dict,
        verbose_name="象限配置"
    )

    display_order = models.IntegerField(default=0, verbose_name="展示顺序")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rotation_template'
        verbose_name = '轮动预设模板'
        verbose_name_plural = '轮动预设模板'
        ordering = ['display_order']

    def __str__(self):
        return self.name


class PortfolioRotationConfigModel(models.Model):
    """
    账户级轮动配置表

    每个投资组合账户（SimulatedAccountModel）独立一份配置。
    保存该账户自己的风险偏好和各象限资产权重，不与其他账户共享。

    架构说明：
    - RotationConfigModel 是全局模板层（管理员维护）
    - PortfolioRotationConfigModel 是账户实例层（每用户每账户独立）
    - 两者通过 base_config 可选关联，账户可以从模板派生也可以完全自定义
    """
    account = models.OneToOneField(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        related_name='rotation_config',
        verbose_name="投资组合账户"
    )
    base_config = models.ForeignKey(
        RotationConfigModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='account_instances',
        verbose_name="基础模板（可选）"
    )

    RISK_TOLERANCE_CHOICES = [
        ('conservative', '保守型'),
        ('moderate', '稳健型'),
        ('aggressive', '激进型'),
    ]
    risk_tolerance = models.CharField(
        max_length=20,
        choices=RISK_TOLERANCE_CHOICES,
        default='moderate',
        verbose_name="风险偏好"
    )

    # 格式：{regime_name: {asset_code: weight(0.0-1.0)}}
    # 每个象限的权重之和必须为 1.0（后端序列化器验证）
    regime_allocations = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="象限资产配置"
    )

    is_enabled = models.BooleanField(
        default=False,
        verbose_name="启用轮动",
        help_text="启用后，自动交易将根据当前 Regime 使用此配置调仓"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_rotation_config'
        verbose_name = '账户轮动配置'
        verbose_name_plural = '账户轮动配置'

    def __str__(self):
        return f"{self.account.account_name} - {self.risk_tolerance}"
