"""
基金分析模块 - 序列化器

遵循项目架构约束：
- 只负责数据格式转换
- 不包含业务逻辑
"""

from rest_framework import serializers
from datetime import date
from decimal import Decimal

from ..application.use_cases import (
    ScreenFundsRequest, ScreenFundsResponse,
    AnalyzeFundStyleRequest, AnalyzeFundStyleResponse,
    CalculateFundPerformanceRequest, CalculateFundPerformanceResponse
)


class ScreenFundsRequestSerializer(serializers.Serializer):
    """筛选基金请求序列化器"""
    regime = serializers.CharField(required=False, allow_null=True)
    custom_types = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True
    )
    custom_styles = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True
    )
    min_scale = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    max_count = serializers.IntegerField(default=30, min_value=1, max_value=100)


class ScreenFundsResponseSerializer(serializers.Serializer):
    """筛选基金响应序列化器"""
    success = serializers.BooleanField()
    regime = serializers.CharField()
    fund_codes = serializers.ListField(child=serializers.CharField())
    fund_names = serializers.ListField(child=serializers.CharField())
    screening_criteria = serializers.DictField()
    error = serializers.CharField(allow_null=True, required=False)


class AnalyzeFundStyleRequestSerializer(serializers.Serializer):
    """分析基金风格请求序列化器"""
    fund_code = serializers.CharField(max_length=10)
    report_date = serializers.DateField(required=False, allow_null=True)


class AnalyzeFundStyleResponseSerializer(serializers.Serializer):
    """分析基金风格响应序列化器"""
    success = serializers.BooleanField()
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    style_weights = serializers.DictField(
        child=serializers.FloatField(),
        help_text="{风格: 权重}"
    )
    sector_concentration = serializers.DictField(
        child=serializers.FloatField(),
        help_text="{指标: 值}"
    )
    error = serializers.CharField(allow_null=True, required=False)


class CalculateFundPerformanceRequestSerializer(serializers.Serializer):
    """计算基金业绩请求序列化器"""
    fund_code = serializers.CharField(max_length=10)
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class FundPerformanceSerializer(serializers.Serializer):
    """基金业绩序列化器"""
    fund_code = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    total_return = serializers.FloatField()
    annualized_return = serializers.FloatField(allow_null=True, required=False)
    volatility = serializers.FloatField(allow_null=True, required=False)
    sharpe_ratio = serializers.FloatField(allow_null=True, required=False)
    max_drawdown = serializers.FloatField(allow_null=True, required=False)
    beta = serializers.FloatField(allow_null=True, required=False)
    alpha = serializers.FloatField(allow_null=True, required=False)


class CalculateFundPerformanceResponseSerializer(serializers.Serializer):
    """计算基金业绩响应序列化器"""
    success = serializers.BooleanField()
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    performance = FundPerformanceSerializer(allow_null=True, required=False)
    error = serializers.CharField(allow_null=True, required=False)


class FundInfoSerializer(serializers.Serializer):
    """基金信息序列化器"""
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    fund_type = serializers.CharField()
    investment_style = serializers.CharField(allow_null=True, required=False)
    setup_date = serializers.DateField(allow_null=True, required=False)
    management_company = serializers.CharField(allow_null=True, required=False)
    custodian = serializers.CharField(allow_null=True, required=False)
    fund_scale = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        allow_null=True,
        required=False
    )


class FundNetValueSerializer(serializers.Serializer):
    """基金净值序列化器"""
    fund_code = serializers.CharField()
    nav_date = serializers.DateField()
    unit_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    accum_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    daily_return = serializers.FloatField(allow_null=True, required=False)


class FundHoldingSerializer(serializers.Serializer):
    """基金持仓序列化器"""
    fund_code = serializers.CharField()
    report_date = serializers.DateField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    holding_amount = serializers.IntegerField(allow_null=True, required=False)
    holding_value = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        allow_null=True,
        required=False
    )
    holding_ratio = serializers.FloatField(allow_null=True, required=False)


class FundScoreSerializer(serializers.Serializer):
    """基金评分序列化器"""
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    score_date = serializers.DateField()
    performance_score = serializers.FloatField()
    regime_fit_score = serializers.FloatField()
    risk_score = serializers.FloatField()
    scale_score = serializers.FloatField()
    total_score = serializers.FloatField()
    rank = serializers.IntegerField()
