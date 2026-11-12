"""Explicit HTTP schemas for two-portfolio comparison."""

from typing import Any

from rest_framework import serializers


class PortfolioComparisonQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Validate two distinct account IDs and one common half-open period."""

    left_account_id = serializers.IntegerField(min_value=1)
    right_account_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Reject ambiguous accounts and empty/reversed periods."""

        if data["left_account_id"] == data["right_account_id"]:
            raise serializers.ValidationError("请选择两个不同的投资组合")
        if data["start_date"] >= data["end_date"]:
            raise serializers.ValidationError("结束日期必须晚于开始日期")
        return data


class ComparisonAccountSerializer(serializers.Serializer[dict[str, Any]]):
    account_id = serializers.IntegerField()
    account_name = serializers.CharField()


class ComparisonMetricSerializer(serializers.Serializer[dict[str, Any]]):
    key = serializers.CharField()
    metric_label = serializers.CharField()
    unit = serializers.CharField()
    left = serializers.FloatField(allow_null=True)
    right = serializers.FloatField(allow_null=True)
    difference = serializers.FloatField(allow_null=True)


class ComparisonCurvePointSerializer(serializers.Serializer[dict[str, Any]]):
    date = serializers.DateField()
    left = serializers.FloatField(allow_null=True)
    right = serializers.FloatField(allow_null=True)


class HoldingComparisonSerializer(serializers.Serializer[dict[str, Any]]):
    asset_code = serializers.CharField()
    asset_name = serializers.CharField()
    industry = serializers.CharField(allow_null=True)
    left_weight_percentage = serializers.FloatField(allow_null=True)
    right_weight_percentage = serializers.FloatField(allow_null=True)
    difference_percentage_points = serializers.FloatField(allow_null=True)


class IndustryComparisonSerializer(serializers.Serializer[dict[str, Any]]):
    industry = serializers.CharField()
    left_weight_percentage = serializers.FloatField(allow_null=True)
    right_weight_percentage = serializers.FloatField(allow_null=True)
    difference_percentage_points = serializers.FloatField(allow_null=True)


class OverlapSummarySerializer(serializers.Serializer[dict[str, Any]]):
    overlap_label = serializers.CharField()
    overlap_percentage = serializers.FloatField(allow_null=True)


class HoldingsComparisonSerializer(serializers.Serializer[dict[str, Any]]):
    overlap_percentage = serializers.FloatField(allow_null=True)
    shared_count = serializers.IntegerField()
    left_only_count = serializers.IntegerField()
    right_only_count = serializers.IntegerField()
    valuation_known = serializers.BooleanField()
    classification_known = serializers.BooleanField()
    rows = HoldingComparisonSerializer(many=True)
    industry_rows = IndustryComparisonSerializer(many=True)
    overlap_rows = OverlapSummarySerializer(many=True)


class PortfolioComparisonResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Document the complete comparison response."""

    success = serializers.BooleanField()
    outcome = serializers.ChoiceField(choices=["success", "partial"])
    left_account = ComparisonAccountSerializer()
    right_account = ComparisonAccountSerializer()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    relative_twr_percentage_points = serializers.FloatField(allow_null=True)
    metrics = ComparisonMetricSerializer(many=True)
    curve = ComparisonCurvePointSerializer(many=True)
    holdings = HoldingsComparisonSerializer()
    warnings = serializers.ListField(child=serializers.CharField())
