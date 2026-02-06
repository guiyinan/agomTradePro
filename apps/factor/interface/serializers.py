"""
Factor Module Interface Layer - Serializers

DRF Serializers for the factor module API.
"""

from rest_framework import serializers
from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorPortfolioConfigModel,
    FactorExposureModel,
    FactorPortfolioHoldingModel,
)


class FactorDefinitionSerializer(serializers.ModelSerializer):
    """Serializer for FactorDefinition"""

    class Meta:
        model = FactorDefinitionModel
        fields = [
            'id', 'code', 'name', 'category', 'description',
            'data_source', 'data_field', 'direction', 'update_frequency',
            'is_active', 'min_data_points', 'allow_missing',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class FactorExposureSerializer(serializers.ModelSerializer):
    """Serializer for FactorExposure"""

    class Meta:
        model = FactorExposureModel
        fields = [
            'id', 'stock_code', 'trade_date', 'factor_code',
            'factor_value', 'percentile_rank', 'z_score', 'normalized_score',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class FactorPortfolioConfigSerializer(serializers.ModelSerializer):
    """Serializer for FactorPortfolioConfig"""

    class Meta:
        model = FactorPortfolioConfigModel
        fields = [
            'id', 'name', 'description', 'factor_weights', 'universe',
            'min_market_cap', 'max_market_cap', 'max_pe', 'min_pe',
            'max_pb', 'max_debt_ratio', 'top_n', 'rebalance_frequency',
            'weight_method', 'max_sector_weight', 'max_single_stock_weight',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class FactorPortfolioHoldingSerializer(serializers.ModelSerializer):
    """Serializer for FactorPortfolioHolding"""

    config_name = serializers.CharField(source='config.name', read_only=True)

    class Meta:
        model = FactorPortfolioHoldingModel
        fields = [
            'id', 'config', 'config_name', 'trade_date', 'stock_code',
            'stock_name', 'weight', 'factor_score', 'rank', 'sector',
            'factor_scores', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class FactorScoreRequestSerializer(serializers.Serializer):
    """Serializer for factor score calculation request"""
    trade_date = serializers.DateField(required=False)
    universe = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
    )
    factor_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
    )


class FactorScoreResponseSerializer(serializers.Serializer):
    """Serializer for factor score response"""
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
