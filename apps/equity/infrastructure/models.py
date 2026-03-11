"""
个股分析模块 Infrastructure 层 ORM 模型

遵循四层架构规范：
- Infrastructure 层允许导入 django.db
- 实现数据持久化逻辑
"""

from django.db import models
from django.utils import timezone
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

    # 可信数据元信息
    source_provider = models.CharField(
        max_length=32,
        default="unknown",
        db_index=True,
        verbose_name="数据提供方"
    )
    source_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="源端更新时间"
    )
    fetched_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="抓取时间"
    )
    pe_type = models.CharField(
        max_length=16,
        default="dynamic",
        db_index=True,
        verbose_name="PE口径"
    )
    is_valid = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否有效"
    )
    quality_flag = models.CharField(
        max_length=32,
        default="ok",
        db_index=True,
        verbose_name="质量标记"
    )
    quality_notes = models.CharField(
        max_length=255,
        default="",
        blank=True,
        verbose_name="质量说明"
    )
    raw_payload_hash = models.CharField(
        max_length=64,
        default="",
        blank=True,
        verbose_name="原始载荷哈希"
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
            models.Index(fields=['stock_code', 'trade_date', 'is_valid']),
            models.Index(fields=['trade_date', 'source_provider']),
            models.Index(fields=['quality_flag', 'trade_date']),
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


class ValuationRepairTrackingModel(models.Model):
    """估值修复跟踪表

    跟踪股票从低估值向合理估值修复的进程，包括修复阶段、进度、速度等指标。
    支持识别修复停滞状态和预测修复完成时间。
    """

    # 股票标识
    stock_code = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代码"
    )
    stock_name = models.CharField(
        max_length=100,
        default="",
        blank=True,
        verbose_name="股票名称"
    )

    # 日期信息
    as_of_date = models.DateField(
        db_index=True,
        verbose_name="数据截止日期"
    )
    repair_start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="修复开始日期"
    )
    repair_start_percentile = models.FloatField(
        null=True,
        blank=True,
        verbose_name="修复起始分位数"
    )

    # 修复状态
    current_phase = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name="当前修复阶段"
    )
    signal = models.CharField(
        max_length=32,
        default="none",
        db_index=True,
        verbose_name="交易信号"
    )

    # 分位数指标
    composite_percentile = models.FloatField(
        verbose_name="综合分位数"
    )
    pe_percentile = models.FloatField(
        null=True,
        blank=True,
        verbose_name="PE分位数"
    )
    pb_percentile = models.FloatField(
        verbose_name="PB分位数"
    )

    # 修复进度指标
    repair_progress = models.FloatField(
        null=True,
        blank=True,
        verbose_name="修复进度(%)"
    )
    repair_speed_per_30d = models.FloatField(
        null=True,
        blank=True,
        verbose_name="修复速度(每30天百分点)"
    )
    estimated_days_to_target = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="预计到达目标天数"
    )

    # 停滞检测
    is_stalled = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="是否停滞"
    )
    stall_start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="停滞开始日期"
    )
    stall_duration_trading_days = models.IntegerField(
        default=0,
        verbose_name="停滞持续交易日数"
    )
    repair_duration_trading_days = models.IntegerField(
        default=0,
        verbose_name="修复持续交易日数"
    )

    # 最低点记录
    lowest_percentile = models.FloatField(
        verbose_name="最低分位数"
    )
    lowest_percentile_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="最低分位数日期"
    )

    # 配置参数
    target_percentile = models.FloatField(
        default=0.5,
        verbose_name="目标分位数"
    )
    composite_method = models.CharField(
        max_length=20,
        default="pb_only",
        verbose_name="综合分位数方法"
    )
    confidence = models.FloatField(
        default=0.0,
        verbose_name="置信度"
    )

    # 股票池来源
    source_universe = models.CharField(
        max_length=32,
        default="all_active",
        db_index=True,
        verbose_name="来源股票池"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否活跃"
    )

    # 元数据
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = 'equity_valuation_repair_tracking'
        verbose_name = '估值修复跟踪'
        verbose_name_plural = '估值修复跟踪'
        unique_together = [["stock_code", "source_universe"]]
        indexes = [
            models.Index(fields=["source_universe", "current_phase"]),
            models.Index(fields=["source_universe", "signal"]),
            models.Index(fields=["as_of_date"]),
        ]
        ordering = ["-composite_percentile", "stock_code"]

    def __str__(self):
        return f"{self.stock_code} - {self.current_phase} ({self.composite_percentile:.2f})"


class ValuationDataQualitySnapshotModel(models.Model):
    """估值数据质量快照表"""

    as_of_date = models.DateField(
        unique=True,
        db_index=True,
        verbose_name="数据日期"
    )
    expected_stock_count = models.IntegerField(default=0, verbose_name="预期股票数")
    synced_stock_count = models.IntegerField(default=0, verbose_name="同步股票数")
    valid_stock_count = models.IntegerField(default=0, verbose_name="有效股票数")

    coverage_ratio = models.FloatField(default=0.0, verbose_name="覆盖率")
    valid_ratio = models.FloatField(default=0.0, verbose_name="有效率")

    missing_pb_count = models.IntegerField(default=0, verbose_name="PB缺失数")
    invalid_pb_count = models.IntegerField(default=0, verbose_name="PB非法数")
    missing_pe_count = models.IntegerField(default=0, verbose_name="PE缺失数")
    jump_alert_count = models.IntegerField(default=0, verbose_name="跳变告警数")
    source_deviation_count = models.IntegerField(default=0, verbose_name="源偏差数")

    primary_source = models.CharField(
        max_length=32,
        default="akshare",
        verbose_name="主数据源"
    )
    fallback_used_count = models.IntegerField(default=0, verbose_name="备源使用数")

    is_gate_passed = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="是否通过门禁"
    )
    gate_reason = models.CharField(
        max_length=255,
        default="",
        blank=True,
        verbose_name="门禁原因"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "equity_valuation_quality_snapshot"
        verbose_name = "估值数据质量快照"
        verbose_name_plural = "估值数据质量快照"
        ordering = ["-as_of_date"]
        indexes = [
            models.Index(fields=["as_of_date", "is_gate_passed"]),
        ]

    def __str__(self):
        return f"{self.as_of_date} gate={'pass' if self.is_gate_passed else 'fail'}"


class ValuationRepairConfigModel(models.Model):
    """估值修复策略参数配置表

    支持在线调参，包含版本控制、生效时间和审计。
    同一时间只能有一个 is_active=True 的配置生效。
    """

    # ============== 版本与状态 ==============
    version = models.IntegerField(
        default=1,
        verbose_name="版本号"
    )
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="是否激活（生效中）"
    )
    effective_from = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="生效时间"
    )

    # ============== 历史数据要求 ==============
    min_history_points = models.IntegerField(
        default=120,
        verbose_name="最小历史样本数"
    )
    default_lookback_days = models.IntegerField(
        default=756,
        verbose_name="默认回看交易日数"
    )

    # ============== 修复确认参数 ==============
    confirm_window = models.IntegerField(
        default=20,
        verbose_name="修复确认窗口（交易日）"
    )
    min_rebound = models.FloatField(
        default=0.05,
        verbose_name="最小反弹幅度（百分位）"
    )

    # ============== 停滞检测参数 ==============
    stall_window = models.IntegerField(
        default=40,
        verbose_name="停滞检测窗口（交易日）"
    )
    stall_min_progress = models.FloatField(
        default=0.02,
        verbose_name="停滞最小进展阈值"
    )

    # ============== 阶段判定阈值 ==============
    target_percentile = models.FloatField(
        default=0.50,
        verbose_name="目标百分位"
    )
    undervalued_threshold = models.FloatField(
        default=0.20,
        verbose_name="低估阈值"
    )
    near_target_threshold = models.FloatField(
        default=0.45,
        verbose_name="接近目标阈值"
    )
    overvalued_threshold = models.FloatField(
        default=0.80,
        verbose_name="高估阈值"
    )

    # ============== 复合百分位权重 ==============
    pe_weight = models.FloatField(
        default=0.6,
        verbose_name="PE 权重"
    )
    pb_weight = models.FloatField(
        default=0.4,
        verbose_name="PB 权重"
    )

    # ============== 置信度计算参数 ==============
    confidence_base = models.FloatField(
        default=0.4,
        verbose_name="置信度基础值"
    )
    confidence_sample_threshold = models.IntegerField(
        default=252,
        verbose_name="置信度样本数阈值"
    )
    confidence_sample_bonus = models.FloatField(
        default=0.2,
        verbose_name="置信度样本数奖励"
    )
    confidence_blend_bonus = models.FloatField(
        default=0.15,
        verbose_name="置信度 pe_pb_blend 奖励"
    )
    confidence_repair_start_bonus = models.FloatField(
        default=0.15,
        verbose_name="置信度修复起点奖励"
    )
    confidence_not_stalled_bonus = models.FloatField(
        default=0.1,
        verbose_name="置信度非停滞奖励"
    )

    # ============== 其他阈值 ==============
    repairing_threshold = models.FloatField(
        default=0.10,
        verbose_name="REPAIRING 阶段阈值"
    )
    eta_max_days = models.IntegerField(
        default=999,
        verbose_name="ETA 最大天数"
    )

    # ============== 审计字段 ==============
    change_reason = models.TextField(
        default="",
        blank=True,
        verbose_name="变更原因"
    )
    created_by = models.CharField(
        max_length=64,
        default="",
        blank=True,
        verbose_name="创建人"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "equity_valuation_repair_config"
        verbose_name = "估值修复策略参数"
        verbose_name_plural = "估值修复策略参数"
        ordering = ["-version"]
        indexes = [
            models.Index(fields=["is_active", "effective_from"]),
            models.Index(fields=["version"]),
        ]

    def __str__(self):
        status = "ACTIVE" if self.is_active else "DRAFT"
        return f"Config v{self.version} [{status}]"

    def save(self, *args, **kwargs):
        """保存时自动处理版本号和激活状态"""
        # 新建记录时自动计算版本号
        if not self.pk:
            max_version = ValuationRepairConfigModel.objects.aggregate(
                max_v=models.Max('version')
            )['max_v'] or 0
            self.version = max_version + 1

        # 如果设置为激活，先停用其他配置
        if self.is_active:
            ValuationRepairConfigModel.objects.filter(
                is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
            if not self.effective_from:
                self.effective_from = timezone.now()

        super().save(*args, **kwargs)

    @classmethod
    def get_active_config(cls):
        """获取当前激活的配置"""
        return cls.objects.filter(is_active=True).first()

    def to_domain_config(self):
        """转换为 Domain 层配置对象"""
        from apps.equity.domain.entities_valuation_repair import ValuationRepairConfig
        return ValuationRepairConfig(
            min_history_points=self.min_history_points,
            default_lookback_days=self.default_lookback_days,
            confirm_window=self.confirm_window,
            min_rebound=self.min_rebound,
            stall_window=self.stall_window,
            stall_min_progress=self.stall_min_progress,
            target_percentile=self.target_percentile,
            undervalued_threshold=self.undervalued_threshold,
            near_target_threshold=self.near_target_threshold,
            overvalued_threshold=self.overvalued_threshold,
            pe_weight=self.pe_weight,
            pb_weight=self.pb_weight,
            confidence_base=self.confidence_base,
            confidence_sample_threshold=self.confidence_sample_threshold,
            confidence_sample_bonus=self.confidence_sample_bonus,
            confidence_blend_bonus=self.confidence_blend_bonus,
            confidence_repair_start_bonus=self.confidence_repair_start_bonus,
            confidence_not_stalled_bonus=self.confidence_not_stalled_bonus,
            repairing_threshold=self.repairing_threshold,
            eta_max_days=self.eta_max_days,
        )
