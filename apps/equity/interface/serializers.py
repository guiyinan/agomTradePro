"""
个股分析模块 Interface 层序列化器

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
"""

from rest_framework import serializers
from decimal import Decimal


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


class AnalyzeValuationResponseSerializer(serializers.Serializer):
    """估值分析响应序列化器"""

    success = serializers.BooleanField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    current_pe = serializers.FloatField()
    pe_percentile = serializers.FloatField()
    current_pb = serializers.FloatField()
    pb_percentile = serializers.FloatField()
    is_undervalued = serializers.BooleanField()
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
    beta = serializers.FloatField(help_text="Beta 系数")
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

class ValuationRepairConfigSerializer(serializers.ModelSerializer):
    """估值修复配置序列化器（读取）"""

    class Meta:
        from apps.equity.infrastructure.models import ValuationRepairConfigModel
        model = ValuationRepairConfigModel
        fields = [
            'id', 'version', 'is_active', 'effective_from',
            # 历史数据要求
            'min_history_points', 'default_lookback_days',
            # 修复确认参数
            'confirm_window', 'min_rebound',
            # 停滞检测参数
            'stall_window', 'stall_min_progress',
            # 阶段判定阈值
            'target_percentile', 'undervalued_threshold',
            'near_target_threshold', 'overvalued_threshold',
            # 复合百分位权重
            'pe_weight', 'pb_weight',
            # 置信度计算参数
            'confidence_base', 'confidence_sample_threshold',
            'confidence_sample_bonus', 'confidence_blend_bonus',
            'confidence_repair_start_bonus', 'confidence_not_stalled_bonus',
            # 其他阈值
            'repairing_threshold', 'eta_max_days',
            # 审计字段
            'change_reason', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'version', 'created_at', 'updated_at']


class ValuationRepairConfigCreateSerializer(serializers.ModelSerializer):
    """估值修复配置序列化器（创建/更新）"""

    class Meta:
        from apps.equity.infrastructure.models import ValuationRepairConfigModel
        model = ValuationRepairConfigModel
        fields = [
            # 历史数据要求
            'min_history_points', 'default_lookback_days',
            # 修复确认参数
            'confirm_window', 'min_rebound',
            # 停滞检测参数
            'stall_window', 'stall_min_progress',
            # 阶段判定阈值
            'target_percentile', 'undervalued_threshold',
            'near_target_threshold', 'overvalued_threshold',
            # 复合百分位权重
            'pe_weight', 'pb_weight',
            # 置信度计算参数
            'confidence_base', 'confidence_sample_threshold',
            'confidence_sample_bonus', 'confidence_blend_bonus',
            'confidence_repair_start_bonus', 'confidence_not_stalled_bonus',
            # 其他阈值
            'repairing_threshold', 'eta_max_days',
            # 变更原因
            'change_reason',
        ]

    def validate(self, data):
        """验证配置参数合理性"""
        errors = []

        # 权重和应该为 1
        pe_weight = data.get('pe_weight', 0.6)
        pb_weight = data.get('pb_weight', 0.4)
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
        undervalued = data.get('undervalued_threshold', 0.20)
        near_target = data.get('near_target_threshold', 0.45)
        target = data.get('target_percentile', 0.50)
        overvalued = data.get('overvalued_threshold', 0.80)

        if not (undervalued < near_target < target < overvalued):
            errors.append(
                f"阈值应满足: undervalued({undervalued}) < "
                f"near_target({near_target}) < target({target}) < "
                f"overvalued({overvalued})"
            )

        if errors:
            raise serializers.ValidationError({"config": errors})

        return data


# 别名，保持向后兼容
ValuationRepairConfigCreateSerializer = ValuationRepairConfigCreateSerializer
