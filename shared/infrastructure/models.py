"""
Configuration Models for AgomTradePro

存储可在后台配置的参数，替代硬编码。
"""

from decimal import Decimal
from django.db import models
from typing import Dict


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


class TransactionCostConfigModel(models.Model):
    """
    交易成本配置表

    存储不同市场和资产类别的交易成本参数。
    """

    MARKET_CHOICES = [
        ('CN_A_SHARE', 'A股'),
        ('CN_HK_STOCK', '港股'),
        ('US_STOCK', '美股'),
        ('CN_FUND', '基金'),
        ('CN_FUTURES', '期货'),
        ('CRYPTO', '加密货币'),
        ('other', '其他'),
    ]

    ASSET_CLASS_CHOICES = [
        ('equity', '股票'),
        ('fixed_income', '债券'),
        ('fund', '基金'),
        ('derivative', '衍生品'),
        ('other', '其他'),
    ]

    market = models.CharField(
        max_length=20,
        choices=MARKET_CHOICES,
        verbose_name="市场"
    )

    asset_class = models.CharField(
        max_length=20,
        choices=ASSET_CLASS_CHOICES,
        verbose_name="资产类别"
    )

    # 成本参数（均为百分比，如 0.0003 表示 0.03%）
    commission_rate = models.FloatField(
        default=0.0003,
        verbose_name="佣金费率",
        help_text="如 0.0003 表示万分之三"
    )

    slippage_rate = models.FloatField(
        default=0.0002,
        verbose_name="滑点费率",
        help_text="如 0.0002 表示万分之二"
    )

    stamp_duty_rate = models.FloatField(
        default=0.001,
        verbose_name="印花税率",
        help_text="仅卖出时收取，如 0.001 表示千分之一"
    )

    # 其他费用
    transfer_fee_rate = models.FloatField(
        default=0.00001,
        verbose_name="过户费率",
        help_text="如 0.00001 表示万分之一"
    )

    # 最小费用
    min_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5.00,
        verbose_name="最低佣金",
        help_text="单笔交易最低佣金（元）"
    )

    # 成本阈值
    cost_warning_threshold = models.FloatField(
        default=0.005,
        verbose_name="成本预警阈值",
        help_text="成本占交易额比例超过此值时预警，如 0.005 表示 0.5%"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'transaction_cost_config'
        verbose_name = '交易成本配置'
        verbose_name_plural = '交易成本配置'
        unique_together = [['market', 'asset_class']]
        indexes = [
            models.Index(fields=['market', 'asset_class']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.get_market_display()} - {self.get_asset_class_display()}"

    def calculate_total_cost(
        self,
        trade_value: Decimal,
        is_buy: bool = True,
    ) -> Dict[str, Decimal]:
        """
        计算交易总成本

        Args:
            trade_value: 交易金额
            is_buy: 是否买入（印花税仅在卖出时收取）

        Returns:
            成本明细字典
        """
        from decimal import Decimal

        trade_value_float = float(trade_value)

        # 佣金
        commission = max(
            Decimal(str(trade_value_float * self.commission_rate)),
            self.min_commission
        )

        # 滑点
        slippage = Decimal(str(trade_value_float * self.slippage_rate))

        # 印花税（仅卖出）
        stamp_duty = Decimal('0') if is_buy else Decimal(str(trade_value_float * self.stamp_duty_rate))

        # 过户费
        transfer_fee = Decimal(str(trade_value_float * self.transfer_fee_rate))

        # 总成本
        total_cost = commission + slippage + stamp_duty + transfer_fee

        return {
            'commission': commission,
            'slippage': slippage,
            'stamp_duty': stamp_duty,
            'transfer_fee': transfer_fee,
            'total_cost': total_cost,
            'cost_ratio': float(total_cost) / trade_value_float if trade_value_float > 0 else 0,
        }


class HedgingInstrumentConfigModel(models.Model):
    """
    对冲工具配置表

    存储可用于对冲的金融工具信息。
    """

    INSTRUMENT_TYPE_CHOICES = [
        ('futures', '期货'),
        ('options', '期权'),
        ('inverse_etf', '反向ETF'),
        ('cash', '现金'),
    ]

    instrument_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="工具代码"
    )

    instrument_name = models.CharField(max_length=100, verbose_name="工具名称")

    instrument_type = models.CharField(
        max_length=20,
        choices=INSTRUMENT_TYPE_CHOICES,
        verbose_name="工具类型"
    )

    # 对冲参数
    hedge_ratio = models.FloatField(
        default=1.0,
        verbose_name="对冲比例",
        help_text="如 0.95 表示需要对冲95%的敞口"
    )

    underlying_index = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="标的指数",
        help_text="如 000300.SH 表示沪深300"
    )

    # 成本参数
    cost_bps = models.FloatField(
        default=5.0,
        verbose_name="对冲成本（基点）",
        help_text="如 5 表示 0.05%"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'hedging_instrument_config'
        verbose_name = '对冲工具配置'
        verbose_name_plural = '对冲工具配置'
        indexes = [
            models.Index(fields=['instrument_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.instrument_name} ({self.instrument_code})"


class StockScreeningRuleConfigModel(models.Model):
    """个股筛选规则配置表"""

    regime = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation"
    )
    rule_name = models.CharField(max_length=100, verbose_name="规则名称")

    # 财务指标阈值
    min_roe = models.FloatField(default=0.0, verbose_name="最低 ROE（%）")
    min_revenue_growth = models.FloatField(
        default=0.0,
        verbose_name="最低营收增长率（%）"
    )
    min_profit_growth = models.FloatField(
        default=0.0,
        verbose_name="最低净利润增长率（%）"
    )
    max_debt_ratio = models.FloatField(
        default=100.0,
        verbose_name="最高资产负债率（%）"
    )

    # 估值指标阈值
    max_pe = models.FloatField(default=999.0, verbose_name="最高 PE")
    max_pb = models.FloatField(default=999.0, verbose_name="最高 PB")
    min_market_cap = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0,
        verbose_name="最低市值（元）"
    )

    # 行业偏好（JSON 数组）
    sector_preference = models.JSONField(
        default=list,
        blank=True,
        verbose_name="偏好行业列表"
    )

    # 筛选数量
    max_count = models.IntegerField(default=50, verbose_name="最多返回个股数量")

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    priority = models.IntegerField(
        default=0,
        verbose_name="优先级（数字越大优先级越高）"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'config_stock_screening_rule'
        verbose_name = '个股筛选规则配置'
        verbose_name_plural = '个股筛选规则配置'
        indexes = [
            models.Index(fields=['regime', 'is_active']),
            models.Index(fields=['regime', 'priority']),
        ]
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f"{self.regime} - {self.rule_name}"


class SectorPreferenceConfigModel(models.Model):
    """板块偏好配置表"""

    regime = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation"
    )
    sector_name = models.CharField(max_length=50, verbose_name="板块名称")
    weight = models.FloatField(
        default=0.5,
        verbose_name="权重（0.0-1.0）",
        help_text="1.0 表示最强偏好，0.0 表示无偏好"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'config_sector_preference'
        verbose_name = '板块偏好配置'
        verbose_name_plural = '板块偏好配置'
        unique_together = [['regime', 'sector_name']]
        indexes = [
            models.Index(fields=['regime', 'is_active']),
        ]

    def __str__(self):
        return f"{self.regime} - {self.sector_name} (权重: {self.weight})"


class FundTypePreferenceConfigModel(models.Model):
    """基金类型偏好配置表"""

    regime = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation"
    )
    fund_type = models.CharField(max_length=50, verbose_name="基金类型")
    style = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="基金风格",
        help_text="如：成长、价值、平衡、商品等"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    priority = models.IntegerField(default=0, verbose_name="优先级")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'config_fund_type_preference'
        verbose_name = '基金类型偏好配置'
        verbose_name_plural = '基金类型偏好配置'
        unique_together = [['regime', 'fund_type', 'style']]
        indexes = [
            models.Index(fields=['regime', 'is_active']),
        ]

    def __str__(self):
        return f"{self.regime} - {self.fund_type} ({self.style})"
