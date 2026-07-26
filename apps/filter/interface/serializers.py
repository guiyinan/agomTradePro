"""
DRF Serializers for Filter API.
"""

import math
from collections.abc import Mapping
from datetime import date
from typing import Any, cast

from rest_framework import serializers


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject request fields outside the published Filter API contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class FiniteFloatField(serializers.FloatField):
    """Float field that rejects booleans, NaN, and infinities."""

    def to_internal_value(self, data: Any) -> float:
        """Return one finite float or raise a field validation error."""

        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("A finite number is required.")
        return value


def _validate_date_range(data: dict[str, Any]) -> dict[str, Any]:
    """Reject request windows whose end precedes their start."""

    start_date = cast(date | None, data.get("start_date"))
    end_date = cast(date | None, data.get("end_date"))
    if start_date is not None and end_date is not None and start_date > end_date:
        raise serializers.ValidationError(
            {"end_date": ["Must be greater than or equal to start_date."]}
        )
    return data


class FilterTypeSerializer(serializers.Serializer[Any]):
    """滤波器类型序列化器"""

    value = serializers.CharField()
    display = serializers.CharField()


class FilterResultSerializer(serializers.Serializer[Any]):
    """滤波结果序列化器"""

    date = serializers.DateField()
    original_value = serializers.FloatField()
    filtered_value = serializers.FloatField()
    trend = serializers.FloatField(allow_null=True)
    slope = serializers.FloatField(allow_null=True)


class FilterSeriesSerializer(serializers.Serializer[Any]):
    """滤波序列序列化器"""

    indicator_code = serializers.CharField()
    filter_type = serializers.ChoiceField(choices=["HP", "KALMAN"])
    params = serializers.DictField()
    results = FilterResultSerializer(many=True)
    calculated_at = serializers.DateField()

    # 可序列化的聚合数据
    dates = serializers.ListField(child=serializers.CharField())
    original_values = serializers.ListField(child=serializers.FloatField())
    filtered_values = serializers.ListField(child=serializers.FloatField())
    slopes = serializers.ListField(child=serializers.FloatField(allow_null=True))


class ApplyFilterRequestSerializer(StrictFieldsSerializer):
    """应用滤波器请求序列化器"""

    indicator_code = serializers.CharField(
        max_length=50,
        help_text="指标代码 (e.g., PMI, CPI)",
    )
    filter_type = serializers.ChoiceField(
        choices=["HP", "KALMAN"],
        help_text="滤波器类型",
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=200, min_value=1, max_value=1000)
    save_results = serializers.BooleanField(default=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the optional calculation date window."""

        return _validate_date_range(data)


class ApplyFilterResponseSerializer(serializers.Serializer[Any]):
    """应用滤波器响应序列化器"""

    success = serializers.BooleanField()
    series = FilterSeriesSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())


class GetFilterDataRequestSerializer(StrictFieldsSerializer):
    """获取滤波数据请求序列化器"""

    indicator_code = serializers.CharField(max_length=50)
    filter_type = serializers.ChoiceField(choices=["HP", "KALMAN"])
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the optional persisted-data date window."""

        return _validate_date_range(data)


class GetFilterDataResponseSerializer(serializers.Serializer[Any]):
    """获取滤波数据响应序列化器"""

    success = serializers.BooleanField()
    dates = serializers.ListField(child=serializers.CharField())
    original_values = serializers.ListField(child=serializers.FloatField())
    filtered_values = serializers.ListField(child=serializers.FloatField())
    slopes = serializers.ListField(child=serializers.FloatField(allow_null=True))
    error = serializers.CharField(allow_null=True)


class CompareFiltersRequestSerializer(StrictFieldsSerializer):
    """对比滤波器请求序列化器"""

    indicator_code = serializers.CharField(max_length=50)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=200, min_value=1, max_value=1000)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the comparison date window and bounded limit."""

        return _validate_date_range(data)


class CompareFiltersResponseSerializer(serializers.Serializer[Any]):
    """对比滤波器响应序列化器"""

    success = serializers.BooleanField()
    hp_results = FilterSeriesSerializer(allow_null=True)
    kalman_results = FilterSeriesSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)


class KalmanStateSerializer(serializers.Serializer[Any]):
    """Kalman 状态序列化器"""

    level = serializers.FloatField()
    slope = serializers.FloatField()
    level_variance = serializers.FloatField()
    slope_variance = serializers.FloatField()
    level_slope_cov = serializers.FloatField()
    updated_at = serializers.DateField()


class FilterConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """滤波器配置序列化器"""

    indicator_code = serializers.CharField()
    hp_enabled = serializers.BooleanField()
    hp_lambda = serializers.FloatField()
    kalman_enabled = serializers.BooleanField()
    kalman_level_variance = serializers.FloatField()
    kalman_slope_variance = serializers.FloatField()
    kalman_observation_variance = serializers.FloatField()
    description = serializers.CharField(required=False, allow_blank=True)


class UpdateFilterConfigRequestSerializer(StrictFieldsSerializer):
    """Update one filter config override."""

    hp_enabled = serializers.BooleanField(required=False)
    hp_lambda = FiniteFloatField(required=False, min_value=0)
    kalman_enabled = serializers.BooleanField(required=False)
    kalman_level_variance = FiniteFloatField(required=False, min_value=0)
    kalman_slope_variance = FiniteFloatField(required=False, min_value=0)
    kalman_observation_variance = FiniteFloatField(required=False, min_value=0)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Reject empty configuration mutations."""

        if not data:
            raise serializers.ValidationError("At least one config field is required.")
        if data.get("kalman_observation_variance") == 0:
            raise serializers.ValidationError(
                {"kalman_observation_variance": ["Must be greater than zero."]}
            )
        return data
