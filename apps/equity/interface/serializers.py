"""
个股分析模块 Interface 层序列化器

遵循四层架构规范：
- Interface 层只做输入验证和输出格式化
- 禁止业务逻辑
"""

from rest_framework import serializers


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
