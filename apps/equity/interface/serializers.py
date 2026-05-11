"""
个股分析模块 Interface 层序列化器

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
"""

from rest_framework import serializers

from apps.equity.domain.entities_valuation_repair import DEFAULT_VALUATION_REPAIR_CONFIG


class ScreenStocksRequestSerializer(serializers.Serializer):
    """筛选个股请求序列化器"""

    regime = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Regime（可选，不填则自动获取最新）"
    )
    custom_rule = serializers.JSONField(
        required=False,
        help_text="自定义规则（可选）"
    )
    max_count = serializers.IntegerField(
        required=False,
        default=30,
        min_value=1,
        max_value=100,
        help_text="最多返回个股数量"
    )


class ScreenStocksResponseSerializer(serializers.Serializer):
    """筛选个股响应序列化器"""

    success = serializers.BooleanField()
    regime = serializers.CharField()
    stock_codes = serializers.ListField(child=serializers.CharField())
    items = serializers.ListField(child=serializers.DictField(), required=False)
    screening_criteria = serializers.DictField()
    error = serializers.CharField(allow_null=True, required=False)


class AnalyzeValuationRequestSerializer(serializers.Serializer):
    """估值分析请求序列化器"""

    stock_code = serializers.CharField(
        required=True,
        help_text="股票代码"
    )
    lookback_days = serializers.IntegerField(
        required=False,
        default=252,
        min_value=30,
        max_value=1260,
        help_text="回看天数（默认 252，即 1 年）"
    )


class LatestValuationSerializer(serializers.Serializer):
    """最新估值数据序列化器"""
    pe = serializers.FloatField(allow_null=True)
    pb = serializers.FloatField(allow_null=True)
    ps = serializers.FloatField(allow_null=True)
    pe_percentile = serializers.FloatField()
    pb_percentile = serializers.FloatField()
    total_mv = serializers.FloatField(allow_null=True)
    circ_mv = serializers.FloatField(allow_null=True)
    dividend_yield = serializers.FloatField(allow_null=True)
    price = serializers.FloatField(allow_null=True)
    trade_date = serializers.CharField(allow_null=True)
    updated_at = serializers.CharField(allow_null=True, required=False)


class FinancialDataSerializer(serializers.Serializer):
    """财务数据序列化器"""
    roe = serializers.FloatField(allow_null=True)
    roa = serializers.FloatField(allow_null=True)
    revenue = serializers.FloatField(allow_null=True)
    net_profit = serializers.FloatField(allow_null=True)
    revenue_growth = serializers.FloatField(allow_null=True)
    net_profit_growth = serializers.FloatField(allow_null=True)
    debt_ratio = serializers.FloatField(allow_null=True)
    gross_margin = serializers.FloatField(allow_null=True)
    period_end = serializers.CharField(allow_null=True, required=False)
    period_type = serializers.CharField(allow_null=True, required=False)
    report_date = serializers.CharField(allow_null=True)
    source = serializers.CharField(allow_null=True, required=False)
    fetched_at = serializers.CharField(allow_null=True, required=False)


class AnalyzeValuationResponseSerializer(serializers.Serializer):
    """估值分析响应序列化器（个股详情页完整数据）"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    # 基本信息
    sector = serializers.CharField()
    market = serializers.CharField()
    list_date = serializers.CharField(allow_null=True)
    # 估值数据
    current_pe = serializers.FloatField()
    pe_percentile = serializers.FloatField()
    current_pb = serializers.FloatField()
    pb_percentile = serializers.FloatField()
    is_undervalued = serializers.BooleanField()
    # 最新估值详情
    latest_valuation = LatestValuationSerializer(allow_null=True)
    # 财务数据
    financial_data = FinancialDataSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


class TechnicalChartRequestSerializer(serializers.Serializer):
    """技术图表请求序列化器。"""

    stock_code = serializers.CharField(required=True, help_text="股票代码")
    timeframe = serializers.ChoiceField(
        choices=["day", "week", "month"],
        default="day",
        help_text="图表周期",
    )
    lookback_days = serializers.IntegerField(
        required=False,
        default=365,
        min_value=30,
        max_value=2000,
        help_text="回看天数",
    )


class TechnicalChartResponseSerializer(serializers.Serializer):
    """技术图表响应序列化器。"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField(allow_blank=True)
    timeframe = serializers.CharField()
    candles = serializers.ListField(child=serializers.DictField(), required=False)
    signals = serializers.ListField(child=serializers.DictField(), required=False)
    latest_signal = serializers.DictField(required=False, allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)


class IntradayChartRequestSerializer(serializers.Serializer):
    """分时图请求序列化器。"""

    stock_code = serializers.CharField(required=True, help_text="股票代码")


class IntradayChartResponseSerializer(serializers.Serializer):
    """分时图响应序列化器。"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField(allow_blank=True)
    points = serializers.ListField(child=serializers.DictField(), required=False)
    latest_point = serializers.DictField(required=False, allow_null=True)
    session_date = serializers.CharField(allow_null=True, required=False)
    source = serializers.CharField(allow_null=True, required=False)
    error = serializers.CharField(allow_null=True, required=False)


# ============================================================================
# DCF 估值序列化器
# ============================================================================

class CalculateDCFRequestSerializer(serializers.Serializer):
    """DCF 估值请求序列化器"""

    stock_code = serializers.CharField(
        required=True,
        help_text="股票代码"
    )
    growth_rate = serializers.FloatField(
        required=False,
        default=0.1,
        min_value=0.0,
        max_value=1.0,
        help_text="未来增长率（默认 0.1，即 10%）"
    )
    discount_rate = serializers.FloatField(
        required=False,
        default=0.1,
        min_value=0.01,
        max_value=0.5,
        help_text="折现率（默认 0.1，即 10%）"
    )
    terminal_growth = serializers.FloatField(
        required=False,
        default=0.03,
        min_value=0.0,
        max_value=0.1,
        help_text="永续增长率（默认 0.03，即 3%）"
    )
    projection_years = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=10,
        help_text="预测年数（默认 5 年）"
    )


class CalculateDCFResponseSerializer(serializers.Serializer):
    """DCF 估值响应序列化器"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    intrinsic_value = serializers.DecimalField(
        max_digits=22,
        decimal_places=2,
        allow_null=True,
        help_text="内在价值（企业总价值）"
    )
    intrinsic_value_per_share = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
        required=False,
        help_text="每股内在价值"
    )
    current_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
        required=False,
        help_text="当前股价"
    )
    upside = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="上涨空间（百分比）"
    )
    error = serializers.CharField(allow_null=True, required=False)


# ============================================================================
# Regime 相关性分析序列化器
# ============================================================================

class RegimePerformanceSerializer(serializers.Serializer):
    """单个 Regime 表现序列化器"""

    regime = serializers.CharField()
    avg_return = serializers.FloatField(help_text="平均收益率（%）")
    beta = serializers.FloatField(help_text="Beta 系数", allow_null=True)
    sample_days = serializers.IntegerField(help_text="样本天数")


class AnalyzeRegimeCorrelationRequestSerializer(serializers.Serializer):
    """Regime 相关性分析请求序列化器"""

    stock_code = serializers.CharField(
        required=True,
        help_text="股票代码"
    )
    lookback_days = serializers.IntegerField(
        required=False,
        default=1260,
        min_value=252,
        max_value=2520,
        help_text="回看天数（默认 1260，约 5 年）"
    )


class AnalyzeRegimeCorrelationResponseSerializer(serializers.Serializer):
    """Regime 相关性分析响应序列化器"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    regime_performance = RegimePerformanceSerializer(many=True)
    best_regime = serializers.CharField(help_text="最佳 Regime")
    worst_regime = serializers.CharField(help_text="最差 Regime")
    error = serializers.CharField(allow_null=True, required=False)


# ============================================================================
# 综合估值分析序列化器
# ============================================================================

class ComprehensiveValuationRequestSerializer(serializers.Serializer):
    """综合估值分析请求序列化器"""

    stock_code = serializers.CharField(
        required=True,
        help_text="股票代码"
    )
    lookback_days = serializers.IntegerField(
        required=False,
        default=252,
        min_value=60,
        max_value=1260,
        help_text="回看天数（默认 252，约 1 年）"
    )
    industry_avg_pe = serializers.FloatField(
        required=False,
        default=20.0,
        min_value=0,
        help_text="行业平均 PE"
    )
    industry_avg_pb = serializers.FloatField(
        required=False,
        default=2.0,
        min_value=0,
        help_text="行业平均 PB"
    )
    risk_free_rate = serializers.FloatField(
        required=False,
        default=0.03,
        min_value=0.0,
        max_value=0.2,
        help_text="无风险利率（默认 0.03，即 3%）"
    )


class ValuationScoreSerializer(serializers.Serializer):
    """估值评分序列化器"""

    method = serializers.CharField()
    score = serializers.FloatField(help_text="评分（0-100）")
    signal = serializers.ChoiceField(
        choices=['undervalued', 'fair', 'overvalued'],
        help_text="信号"
    )
    details = serializers.JSONField(help_text="详细信息")


class ComprehensiveValuationResponseSerializer(serializers.Serializer):
    """综合估值分析响应序列化器"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    overall_score = serializers.FloatField(help_text="综合评分（0-100）")
    overall_signal = serializers.ChoiceField(
        choices=['strong_buy', 'buy', 'hold', 'sell', 'strong_sell'],
        help_text="综合信号"
    )
    recommendation = serializers.CharField(help_text="推荐建议")
    confidence = serializers.FloatField(help_text="置信度（0-1）")
    scores = ValuationScoreSerializer(many=True, help_text="各方法评分详情")
    error = serializers.CharField(allow_null=True, required=False)


# ============================================================================
# 估值修复跟踪序列化器
# ============================================================================

class ValuationRepairStatusResponseSerializer(serializers.Serializer):
    """估值修复状态响应序列化器"""
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    as_of_date = serializers.DateField()
    phase = serializers.CharField()
    signal = serializers.CharField()
    current_pe = serializers.FloatField(allow_null=True)
    current_pb = serializers.FloatField()
    pe_percentile = serializers.FloatField(allow_null=True)
    pb_percentile = serializers.FloatField()
    composite_percentile = serializers.FloatField()
    composite_method = serializers.CharField()
    repair_start_date = serializers.DateField(allow_null=True)
    repair_start_percentile = serializers.FloatField(allow_null=True)
    lowest_percentile = serializers.FloatField()
    lowest_percentile_date = serializers.DateField()
    repair_progress = serializers.FloatField(allow_null=True)
    target_percentile = serializers.FloatField()
    repair_speed_per_30d = serializers.FloatField(allow_null=True)
    estimated_days_to_target = serializers.IntegerField(allow_null=True)
    is_stalled = serializers.BooleanField()
    stall_start_date = serializers.DateField(allow_null=True)
    stall_duration_trading_days = serializers.IntegerField()
    repair_duration_trading_days = serializers.IntegerField()
    lookback_trading_days = serializers.IntegerField()
    confidence = serializers.FloatField()
    description = serializers.CharField()
    data_quality_flag = serializers.CharField(allow_null=True, required=False)
    data_source_provider = serializers.CharField(required=False)
    data_as_of_date = serializers.DateField(required=False)


class ValuationRepairPointSerializer(serializers.Serializer):
    """估值修复百分位点序列化器"""
    trade_date = serializers.DateField()
    pe_percentile = serializers.FloatField(allow_null=True)
    pb_percentile = serializers.FloatField()
    composite_percentile = serializers.FloatField()
    composite_method = serializers.CharField()


class ValuationRepairHistoryResponseSerializer(serializers.Serializer):
    """估值修复历史响应序列化器"""
    stock_code = serializers.CharField()
    points = ValuationRepairPointSerializer(many=True)
    data_quality_flag = serializers.CharField(allow_null=True, required=False)
    data_source_provider = serializers.CharField(required=False)
    data_as_of_date = serializers.DateField(required=False)


class ScanValuationRepairsRequestSerializer(serializers.Serializer):
    """扫描估值修复请求序列化器"""
    universe = serializers.ChoiceField(
        choices=["all_active", "current_pool"],
        default="all_active"
    )
    lookback_days = serializers.IntegerField(
        default=756,
        min_value=120,
        max_value=1260
    )


class ScanValuationRepairsResponseSerializer(serializers.Serializer):
    """扫描估值修复响应序列化器"""
    success = serializers.BooleanField()
    universe = serializers.CharField()
    as_of_date = serializers.DateField()
    scanned_count = serializers.IntegerField()
    saved_count = serializers.IntegerField()
    phase_counts = serializers.DictField()
    error = serializers.CharField(allow_null=True, required=False)


class ListValuationRepairsRequestSerializer(serializers.Serializer):
    """列出估值修复请求序列化器"""
    universe = serializers.ChoiceField(
        choices=["all_active", "current_pool"],
        default="all_active"
    )
    phase = serializers.CharField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)


class ListValuationRepairsItemSerializer(serializers.Serializer):
    """估值修复列表项序列化器"""
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    phase = serializers.CharField()
    signal = serializers.CharField()
    composite_percentile = serializers.FloatField()
    repair_progress = serializers.FloatField(allow_null=True)
    repair_speed_per_30d = serializers.FloatField(allow_null=True)
    repair_duration_trading_days = serializers.IntegerField()
    estimated_days_to_target = serializers.IntegerField(allow_null=True)
    is_stalled = serializers.BooleanField()
    as_of_date = serializers.DateField()


class ListValuationRepairsResponseSerializer(serializers.Serializer):
    """列出估值修复响应序列化器"""
    success = serializers.BooleanField()
    results = ListValuationRepairsItemSerializer(many=True)


class ValidateValuationDataRequestSerializer(serializers.Serializer):
    """估值数据质量校验请求序列化器"""
    as_of_date = serializers.DateField(required=False)
    primary_source = serializers.CharField(required=False, default="akshare")


class SyncValuationDataRequestSerializer(serializers.Serializer):
    """估值数据同步请求序列化器"""
    stock_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False,
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    days_back = serializers.IntegerField(required=False, default=1, min_value=1, max_value=3650)
    primary_source = serializers.CharField(required=False, default="akshare")
    fallback_source = serializers.CharField(required=False, default="tushare")


class SyncValuationDataResponseSerializer(serializers.Serializer):
    """估值数据同步响应序列化器"""
    requested_count = serializers.IntegerField()
    synced_count = serializers.IntegerField()
    fallback_used_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    errors = serializers.ListField(child=serializers.CharField())


class SyncFinancialDataRequestSerializer(serializers.Serializer):
    """财务数据同步请求序列化器"""

    stock_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False,
    )
    periods = serializers.IntegerField(required=False, default=8, min_value=1, max_value=32)
    source = serializers.CharField(required=False, default="akshare")


class SyncFinancialDataResponseSerializer(serializers.Serializer):
    """财务数据同步响应序列化器"""

    success = serializers.BooleanField()
    synced_count = serializers.IntegerField(required=False)
    error_count = serializers.IntegerField(required=False)
    total_stocks = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)
    errors = serializers.ListField(child=serializers.CharField(), required=False)


class ValuationQualitySnapshotResponseSerializer(serializers.Serializer):
    """估值数据质量快照响应序列化器"""
    as_of_date = serializers.DateField()
    expected_stock_count = serializers.IntegerField()
    synced_stock_count = serializers.IntegerField()
    valid_stock_count = serializers.IntegerField()
    coverage_ratio = serializers.FloatField()
    valid_ratio = serializers.FloatField()
    missing_pb_count = serializers.IntegerField()
    invalid_pb_count = serializers.IntegerField()
    missing_pe_count = serializers.IntegerField()
    jump_alert_count = serializers.IntegerField()
    source_deviation_count = serializers.IntegerField()
    primary_source = serializers.CharField()
    fallback_used_count = serializers.IntegerField()
    is_gate_passed = serializers.BooleanField()
    gate_reason = serializers.CharField(allow_blank=True)


class ValuationFreshnessResponseSerializer(serializers.Serializer):
    """估值数据新鲜度响应序列化器"""
    latest_trade_date = serializers.DateField()
    lag_days = serializers.IntegerField()
    freshness_status = serializers.CharField()
    coverage_ratio = serializers.FloatField(allow_null=True)
    is_gate_passed = serializers.BooleanField(allow_null=True)


# ============== 估值修复配置序列化器 ==============

class ValuationRepairConfigSerializer(serializers.Serializer):
    """估值修复配置序列化器（读取）"""

    id = serializers.IntegerField(read_only=True)
    version = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    effective_from = serializers.DateTimeField(allow_null=True, read_only=True)
    min_history_points = serializers.IntegerField(read_only=True)
    default_lookback_days = serializers.IntegerField(read_only=True)
    confirm_window = serializers.IntegerField(read_only=True)
    min_rebound = serializers.FloatField(read_only=True)
    stall_window = serializers.IntegerField(read_only=True)
    stall_min_progress = serializers.FloatField(read_only=True)
    target_percentile = serializers.FloatField(read_only=True)
    undervalued_threshold = serializers.FloatField(read_only=True)
    near_target_threshold = serializers.FloatField(read_only=True)
    overvalued_threshold = serializers.FloatField(read_only=True)
    pe_weight = serializers.FloatField(read_only=True)
    pb_weight = serializers.FloatField(read_only=True)
    confidence_base = serializers.FloatField(read_only=True)
    confidence_sample_threshold = serializers.IntegerField(read_only=True)
    confidence_sample_bonus = serializers.FloatField(read_only=True)
    confidence_blend_bonus = serializers.FloatField(read_only=True)
    confidence_repair_start_bonus = serializers.FloatField(read_only=True)
    confidence_not_stalled_bonus = serializers.FloatField(read_only=True)
    repairing_threshold = serializers.FloatField(read_only=True)
    eta_max_days = serializers.IntegerField(read_only=True)
    change_reason = serializers.CharField(read_only=True)
    created_by = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class ValuationRepairConfigCreateSerializer(serializers.Serializer):
    """估值修复配置序列化器（创建/更新）"""

    min_history_points = serializers.IntegerField(required=False)
    default_lookback_days = serializers.IntegerField(required=False)
    confirm_window = serializers.IntegerField(required=False)
    min_rebound = serializers.FloatField(required=False)
    stall_window = serializers.IntegerField(required=False)
    stall_min_progress = serializers.FloatField(required=False)
    target_percentile = serializers.FloatField(required=False)
    undervalued_threshold = serializers.FloatField(required=False)
    near_target_threshold = serializers.FloatField(required=False)
    overvalued_threshold = serializers.FloatField(required=False)
    pe_weight = serializers.FloatField(required=False)
    pb_weight = serializers.FloatField(required=False)
    confidence_base = serializers.FloatField(required=False)
    confidence_sample_threshold = serializers.IntegerField(required=False)
    confidence_sample_bonus = serializers.FloatField(required=False)
    confidence_blend_bonus = serializers.FloatField(required=False)
    confidence_repair_start_bonus = serializers.FloatField(required=False)
    confidence_not_stalled_bonus = serializers.FloatField(required=False)
    repairing_threshold = serializers.FloatField(required=False)
    eta_max_days = serializers.IntegerField(required=False)
    change_reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        """验证配置参数合理性"""
        errors = []
        defaults = DEFAULT_VALUATION_REPAIR_CONFIG

        # 权重和应该为 1
        pe_weight = data.get('pe_weight', defaults.pe_weight)
        pb_weight = data.get('pb_weight', defaults.pb_weight)
        if abs(pe_weight + pb_weight - 1.0) > 0.01:
            errors.append(f"PE + PB 权重和应为 1.0，当前为 {pe_weight + pb_weight}")

        # 阈值范围检查
        for field in ['target_percentile', 'undervalued_threshold',
                      'near_target_threshold', 'overvalued_threshold',
                      'min_rebound', 'stall_min_progress']:
            value = data.get(field)
            if value is not None and not (0 <= value <= 1):
                errors.append(f"{field} 应在 0-1 范围内")

        # 阈值逻辑检查
        undervalued = data.get('undervalued_threshold', defaults.undervalued_threshold)
        near_target = data.get('near_target_threshold', defaults.near_target_threshold)
        target = data.get('target_percentile', defaults.target_percentile)
        overvalued = data.get('overvalued_threshold', defaults.overvalued_threshold)

        if not (undervalued < near_target < target < overvalued):
            errors.append(
                f"阈值应满足: undervalued({undervalued}) < "
                f"near_target({near_target}) < target({target}) < "
                f"overvalued({overvalued})"
            )

        if errors:
            raise serializers.ValidationError({"config": errors})

        return data
