"""
基金分析模块 - 序列化器

遵循项目架构约束：
- 只负责数据格式转换
- 不包含业务逻辑
"""

from typing import Any, cast

from rest_framework import serializers

REGIME_CHOICES = ("Recovery", "Overheat", "Stagflation", "Deflation")


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject request fields that are not part of the published contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown parameters: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class ScreenFundsRequestSerializer(StrictFieldsSerializer):
    """筛选基金请求序列化器"""

    regime = serializers.ChoiceField(
        choices=REGIME_CHOICES,
        required=False,
        allow_null=True,
    )
    custom_types = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_null=True,
        max_length=20,
    )
    custom_styles = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_null=True,
        max_length=20,
    )
    min_scale = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
    )
    max_count = serializers.IntegerField(default=30, min_value=1, max_value=100)


class RankFundsQuerySerializer(StrictFieldsSerializer):
    """Strict query contract for persisted fund ranking reads."""

    regime = serializers.ChoiceField(choices=REGIME_CHOICES, default="Recovery")
    max_count = serializers.IntegerField(default=50, min_value=1, max_value=200)


class FundScoreQuerySerializer(StrictFieldsSerializer):
    """Validate one-fund score lookup parameters."""

    regime = serializers.ChoiceField(choices=REGIME_CHOICES, default="Recovery")
    as_of_date = serializers.DateField(required=False, allow_null=True)


class ScreenFundsResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """筛选基金响应序列化器"""

    success = serializers.BooleanField()
    regime = serializers.CharField()
    fund_codes = serializers.ListField(child=serializers.CharField())
    fund_names = serializers.ListField(child=serializers.CharField())
    screening_criteria = serializers.DictField()
    error = serializers.CharField(allow_null=True, required=False)


class AnalyzeFundStyleRequestSerializer(StrictFieldsSerializer):
    """分析基金风格请求序列化器"""

    fund_code = serializers.CharField(max_length=10)
    report_date = serializers.DateField(required=False, allow_null=True)


class AnalyzeFundStyleResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """分析基金风格响应序列化器"""

    success = serializers.BooleanField()
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    style_weights = serializers.DictField(child=serializers.FloatField(), help_text="{风格: 权重}")
    sector_concentration = serializers.DictField(
        child=serializers.FloatField(), help_text="{指标: 值}"
    )
    error = serializers.CharField(allow_null=True, required=False)


class CalculateFundPerformanceRequestSerializer(StrictFieldsSerializer):
    """计算基金业绩请求序列化器"""

    fund_code = serializers.CharField(max_length=10)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject reversed performance windows."""

        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"end_date": "end_date must not be before start_date"}
            )
        return attrs


class FundPerformanceSerializer(serializers.Serializer[dict[str, Any]]):
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


class CalculateFundPerformanceResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """计算基金业绩响应序列化器"""

    success = serializers.BooleanField()
    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    performance = FundPerformanceSerializer(allow_null=True, required=False)
    error = serializers.CharField(allow_null=True, required=False)


class FundInfoSerializer(serializers.Serializer[dict[str, Any]]):
    """基金信息序列化器"""

    fund_code = serializers.CharField()
    fund_name = serializers.CharField()
    fund_type = serializers.CharField()
    investment_style = serializers.CharField(allow_null=True, required=False)
    setup_date = serializers.DateField(allow_null=True, required=False)
    management_company = serializers.CharField(allow_null=True, required=False)
    custodian = serializers.CharField(allow_null=True, required=False)
    fund_scale = serializers.DecimalField(
        max_digits=20, decimal_places=2, allow_null=True, required=False
    )


class FundNetValueSerializer(serializers.Serializer[dict[str, Any]]):
    """基金净值序列化器"""

    fund_code = serializers.CharField()
    nav_date = serializers.DateField()
    unit_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    accum_nav = serializers.DecimalField(max_digits=10, decimal_places=4)
    daily_return = serializers.FloatField(allow_null=True, required=False)


class FundHoldingSerializer(serializers.Serializer[dict[str, Any]]):
    """基金持仓序列化器"""

    fund_code = serializers.CharField()
    report_date = serializers.DateField()
    stock_code = serializers.CharField()
    stock_name = serializers.CharField()
    holding_amount = serializers.IntegerField(allow_null=True, required=False)
    holding_value = serializers.DecimalField(
        max_digits=20, decimal_places=2, allow_null=True, required=False
    )
    holding_ratio = serializers.FloatField(allow_null=True, required=False)


class FundScoreSerializer(serializers.Serializer[dict[str, Any]]):
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


class FundNavQuerySerializer(StrictFieldsSerializer):
    """Validate optional NAV history bounds."""

    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject reversed NAV windows."""

        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise serializers.ValidationError(
                {"end_date": "end_date must not be before start_date"}
            )
        return attrs


class FundHoldingQuerySerializer(StrictFieldsSerializer):
    """Validate an optional holding report date."""

    report_date = serializers.DateField(required=False, allow_null=True)


class FundMultiDimFiltersSerializer(StrictFieldsSerializer):
    """Validate supported multi-dimensional fund filters."""

    fund_type = serializers.CharField(required=False, max_length=50)
    investment_style = serializers.CharField(required=False, max_length=50)
    min_scale = serializers.DecimalField(
        required=False,
        max_digits=20,
        decimal_places=2,
        min_value=0,
    )
    max_scale = serializers.DecimalField(
        required=False,
        max_digits=20,
        decimal_places=2,
        min_value=0,
    )
    fund_company = serializers.CharField(required=False, max_length=100)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject inverted scale ranges."""

        minimum = attrs.get("min_scale")
        maximum = attrs.get("max_scale")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise serializers.ValidationError(
                {"max_scale": "max_scale must not be below min_scale"}
            )
        return attrs


class FundMultiDimContextSerializer(StrictFieldsSerializer):
    """Require explicit, truthful macro context for scoring."""

    regime = serializers.ChoiceField(choices=REGIME_CHOICES)
    policy_level = serializers.ChoiceField(choices=("P0", "P1", "P2", "P3"))
    sentiment_index = serializers.FloatField(min_value=-3.0, max_value=3.0)


class FundMultiDimScreenRequestSerializer(StrictFieldsSerializer):
    """Validate the complete multi-dimensional screening request."""

    filters = FundMultiDimFiltersSerializer(required=False, default=dict)
    macro_context = serializers.DictField(source="context")
    max_count = serializers.IntegerField(default=30, min_value=1, max_value=100)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Keep the public key named ``context`` without shadowing DRF context."""

        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected an object payload.")
        if "macro_context" in data:
            raise serializers.ValidationError(
                {"non_field_errors": ["Unknown parameters: macro_context"]}
            )
        remapped = dict(data)
        if "context" in remapped:
            remapped["macro_context"] = remapped.pop("context")
        return super().to_internal_value(remapped)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize the nested macro context."""

        context_serializer = FundMultiDimContextSerializer(data=attrs.get("context", {}))
        context_serializer.is_valid(raise_exception=True)
        attrs["context"] = context_serializer.validated_data
        return attrs
