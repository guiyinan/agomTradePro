"""
Rotation Module Interface Layer - Serializers

DRF Serializers for the rotation module API.
"""

from rest_framework import serializers
from apps.rotation.infrastructure.models import (
    AssetClassModel,
    RotationConfigModel,
    RotationSignalModel,
    RotationPortfolioModel,
    MomentumScoreModel,
)


class AssetClassSerializer(serializers.ModelSerializer):
    """Serializer for AssetClass"""

    class Meta:
        model = AssetClassModel
        fields = [
            'id', 'code', 'name', 'category', 'description',
            'underlying_index', 'currency', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RotationConfigSerializer(serializers.ModelSerializer):
    """Serializer for RotationConfig"""

    class Meta:
        model = RotationConfigModel
        fields = [
            'id', 'name', 'description', 'strategy_type',
            'asset_universe', 'params', 'rebalance_frequency',
            'min_weight', 'max_weight', 'max_turnover',
            'lookback_period', 'regime_allocations',
            'momentum_periods', 'top_n', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RotationSignalSerializer(serializers.ModelSerializer):
    """Serializer for RotationSignal"""
    config_name = serializers.CharField(source='config.name', read_only=True)

    class Meta:
        model = RotationSignalModel
        fields = [
            'id', 'config', 'config_name', 'signal_date',
            'target_allocation', 'current_regime', 'momentum_ranking',
            'expected_volatility', 'expected_return',
            'action_required', 'reason', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class RotationPortfolioSerializer(serializers.ModelSerializer):
    """Serializer for RotationPortfolio"""
    config_name = serializers.CharField(source='config.name', read_only=True)

    class Meta:
        model = RotationPortfolioModel
        fields = [
            'id', 'config', 'config_name', 'trade_date',
            'current_allocation', 'daily_return', 'cumulative_return',
            'portfolio_volatility', 'max_drawdown', 'turnover_since_last',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class MomentumScoreSerializer(serializers.ModelSerializer):
    """Serializer for MomentumScore"""

    class Meta:
        model = MomentumScoreModel
        fields = [
            'id', 'asset_code', 'calc_date',
            'momentum_1m', 'momentum_3m', 'momentum_6m', 'momentum_12m',
            'composite_score', 'rank',
            'sharpe_1m', 'sharpe_3m',
            'ma_signal', 'trend_strength',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class RotationSignalRequestSerializer(serializers.Serializer):
    """Serializer for rotation signal request"""
    signal_date = serializers.DateField(required=False)
