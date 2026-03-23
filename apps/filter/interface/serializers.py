"""
DRF Serializers for Filter API.
"""

from rest_framework import serializers

from ..domain.entities import FilterResult, FilterSeries, FilterType, KalmanFilterState


class FilterTypeSerializer(serializers.Serializer):
    """滤波器类型序列化器"""
    value = serializers.CharField()
    display = serializers.CharField()


class FilterResultSerializer(serializers.Serializer):
    """滤波结果序列化器"""
    date = serializers.DateField()
    original_value = serializers.FloatField()
    filtered_value = serializers.FloatField()
    trend = serializers.FloatField(allow_null=True)
    slope = serializers.FloatField(allow_null=True)


class FilterSeriesSerializer(serializers.Serializer):
    """滤波序列序列化器"""
    indicator_code = serializers.CharField()
    filter_type = serializers.ChoiceField(choices=['HP', 'KALMAN'])
    params = serializers.DictField()
    results = FilterResultSerializer(many=True)
    calculated_at = serializers.DateField()

    # 可序列化的聚合数据
    dates = serializers.ListField(child=serializers.CharField())
    original_values = serializers.ListField(child=serializers.FloatField())
    filtered_values = serializers.ListField(child=serializers.FloatField())
    slopes = serializers.ListField(child=serializers.FloatField(allow_null=True))


class ApplyFilterRequestSerializer(serializers.Serializer):
    """应用滤波器请求序列化器"""
    indicator_code = serializers.CharField(
        max_length=50,
        help_text="指标代码 (e.g., PMI, CPI)"
    )
    filter_type = serializers.ChoiceField(
        choices=['HP', 'KALMAN'],
        help_text="滤波器类型"
    )
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=200, min_value=1, max_value=1000)
    save_results = serializers.BooleanField(default=True)


class ApplyFilterResponseSerializer(serializers.Serializer):
    """应用滤波器响应序列化器"""
    success = serializers.BooleanField()
    series = FilterSeriesSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())


class GetFilterDataRequestSerializer(serializers.Serializer):
    """获取滤波数据请求序列化器"""
    indicator_code = serializers.CharField()
    filter_type = serializers.ChoiceField(choices=['HP', 'KALMAN'])
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)


class GetFilterDataResponseSerializer(serializers.Serializer):
    """获取滤波数据响应序列化器"""
    success = serializers.BooleanField()
    dates = serializers.ListField(child=serializers.CharField())
    original_values = serializers.ListField(child=serializers.FloatField())
    filtered_values = serializers.ListField(child=serializers.FloatField())
    slopes = serializers.ListField(child=serializers.FloatField(allow_null=True))
    error = serializers.CharField(allow_null=True)


class CompareFiltersRequestSerializer(serializers.Serializer):
    """对比滤波器请求序列化器"""
    indicator_code = serializers.CharField()
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=200)


class CompareFiltersResponseSerializer(serializers.Serializer):
    """对比滤波器响应序列化器"""
    success = serializers.BooleanField()
    hp_results = FilterSeriesSerializer(allow_null=True)
    kalman_results = FilterSeriesSerializer(allow_null=True)
    error = serializers.CharField(allow_null=True)


class KalmanStateSerializer(serializers.Serializer):
    """Kalman 状态序列化器"""
    level = serializers.FloatField()
    slope = serializers.FloatField()
    level_variance = serializers.FloatField()
    slope_variance = serializers.FloatField()
    level_slope_cov = serializers.FloatField()
    updated_at = serializers.DateField()


class FilterConfigSerializer(serializers.Serializer):
    """滤波器配置序列化器"""
    indicator_code = serializers.CharField()
    hp_enabled = serializers.BooleanField()
    hp_lambda = serializers.FloatField()
    kalman_enabled = serializers.BooleanField()
    kalman_level_variance = serializers.FloatField()
    kalman_slope_variance = serializers.FloatField()
    kalman_observation_variance = serializers.FloatField()
