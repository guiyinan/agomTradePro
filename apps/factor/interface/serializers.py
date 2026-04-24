"""DRF serializers for the factor module API."""

from __future__ import annotations

from rest_framework import serializers


class FactorDefinitionSerializer(serializers.Serializer):
    """Serializer for factor definition payloads."""

    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=100)
    category = serializers.CharField(max_length=20)
    description = serializers.CharField(allow_blank=True, required=False)
    data_source = serializers.CharField(max_length=50)
    data_field = serializers.CharField(max_length=100)
    direction = serializers.CharField(max_length=20, default="positive")
    update_frequency = serializers.CharField(max_length=20, default="daily")
    is_active = serializers.BooleanField(default=True)
    min_data_points = serializers.IntegerField(default=20)
    allow_missing = serializers.BooleanField(default=False)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class FactorExposureSerializer(serializers.Serializer):
    """Serializer for factor exposure payloads."""

    id = serializers.IntegerField(read_only=True)
    stock_code = serializers.CharField(max_length=20)
    trade_date = serializers.DateField()
    factor_code = serializers.CharField(max_length=50)
    factor_value = serializers.DecimalField(max_digits=18, decimal_places=6)
    percentile_rank = serializers.DecimalField(max_digits=5, decimal_places=4)
    z_score = serializers.DecimalField(max_digits=10, decimal_places=6)
    normalized_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    created_at = serializers.DateTimeField(read_only=True)


class FactorPortfolioConfigSerializer(serializers.Serializer):
    """Serializer for factor portfolio configuration payloads."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(allow_blank=True, required=False)
    factor_weights = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
        default=dict,
    )
    universe = serializers.CharField(max_length=20, default="all_a")
    min_market_cap = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    max_market_cap = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    max_pe = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    min_pe = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    max_pb = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
    )
    max_debt_ratio = serializers.FloatField(required=False, allow_null=True)
    top_n = serializers.IntegerField(default=30)
    rebalance_frequency = serializers.CharField(max_length=20, default="monthly")
    weight_method = serializers.CharField(max_length=50, default="equal_weight")
    max_sector_weight = serializers.FloatField(required=False, default=0.4)
    max_single_stock_weight = serializers.FloatField(required=False, default=0.05)
    is_active = serializers.BooleanField(default=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class FactorPortfolioHoldingSerializer(serializers.Serializer):
    """Serializer for factor portfolio holding payloads."""

    id = serializers.IntegerField(read_only=True)
    config = serializers.IntegerField(source="config_id")
    config_name = serializers.CharField(source="config.name", read_only=True)
    trade_date = serializers.DateField()
    stock_code = serializers.CharField(max_length=20)
    stock_name = serializers.CharField(max_length=100)
    weight = serializers.DecimalField(max_digits=10, decimal_places=6)
    factor_score = serializers.DecimalField(max_digits=10, decimal_places=4)
    rank = serializers.IntegerField()
    sector = serializers.CharField(max_length=50, allow_blank=True, required=False)
    factor_scores = serializers.DictField(required=False)
    created_at = serializers.DateTimeField(read_only=True)


class FactorScoreRequestSerializer(serializers.Serializer):
    """Serializer for factor score calculation requests."""

    trade_date = serializers.DateField(required=False)
    universe = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
    )
    factor_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
    )
    factor_weights = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
        default=dict,
    )
    top_n = serializers.IntegerField(required=False, default=50)


class FactorScoreResponseSerializer(serializers.Serializer):
    """Serializer for factor score responses."""

    stock_code = serializers.CharField(max_length=20)
    stock_name = serializers.CharField(max_length=100)
    composite_score = serializers.FloatField()
    percentile_rank = serializers.FloatField()
    factor_scores = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
    )
    sector = serializers.CharField(max_length=50, required=False, allow_blank=True)
    market_cap = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
