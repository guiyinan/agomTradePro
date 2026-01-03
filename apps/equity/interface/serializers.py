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
