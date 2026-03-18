"""
Hedge Module Interface Layer - Serializers

DRF Serializers for the hedge module API.
"""

from rest_framework import serializers
from apps.hedge.infrastructure.models import (
    HedgePairModel,
    CorrelationHistoryModel,
    HedgePortfolioSnapshotModel,
    HedgeAlertModel,
    HedgePerformanceModel,
)


class HedgePairSerializer(serializers.ModelSerializer):
    """Serializer for HedgePair"""

    class Meta:
        model = HedgePairModel
        fields = [
            'id', 'name', 'long_asset', 'hedge_asset', 'hedge_method',
            'target_long_weight', 'target_hedge_weight',
            'rebalance_trigger', 'correlation_window',
            'min_correlation', 'max_correlation', 'correlation_alert_threshold',
            'max_hedge_cost', 'beta_target', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CorrelationHistorySerializer(serializers.ModelSerializer):
    """Serializer for CorrelationHistory"""

    class Meta:
        model = CorrelationHistoryModel
        fields = [
            'id', 'asset1', 'asset2', 'calc_date', 'window_days',
            'correlation', 'covariance', 'beta',
            'p_value', 'standard_error',
            'correlation_trend', 'correlation_ma',
            'alert', 'alert_type', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class HedgePortfolioSnapshotSerializer(serializers.ModelSerializer):
    """Serializer for HedgePortfolioSnapshot"""
    pair_name = serializers.CharField(source='pair.name', read_only=True)

    class Meta:
        model = HedgePortfolioSnapshotModel
        fields = [
            'id', 'pair', 'pair_name', 'trade_date',
            'long_weight', 'hedge_weight',
            'hedge_ratio', 'target_hedge_ratio',
            'current_correlation', 'correlation_20d', 'correlation_60d',
            'portfolio_beta', 'portfolio_volatility', 'hedge_effectiveness',
            'daily_return', 'unhedged_return', 'hedge_return',
            'value_at_risk', 'max_drawdown',
            'rebalance_needed', 'rebalance_reason',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class HedgeAlertSerializer(serializers.ModelSerializer):
    """Serializer for HedgeAlert"""

    class Meta:
        model = HedgeAlertModel
        fields = [
            'id', 'pair_name', 'alert_date', 'alert_type',
            'severity', 'message', 'current_value', 'threshold_value',
            'action_required', 'action_priority',
            'is_resolved', 'resolved_at', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'resolved_at']


class HedgePerformanceSerializer(serializers.ModelSerializer):
    """Serializer for HedgePerformance"""

    class Meta:
        model = HedgePerformanceModel
        fields = [
            'id', 'pair_name', 'period_start', 'period_end',
            'total_return', 'annual_return', 'sharpe_ratio',
            'volatility_reduction', 'drawdown_reduction', 'hedge_effectiveness',
            'hedge_cost', 'cost_benefit_ratio',
            'avg_correlation', 'correlation_stability',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class HedgeEffectivenessRequestSerializer(serializers.Serializer):
    """Serializer for hedge effectiveness request"""
    lookback_days = serializers.IntegerField(default=60, required=False)


class CorrelationMatrixRequestSerializer(serializers.Serializer):
    """Serializer for correlation matrix request"""
    asset_codes = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=True,
    )
    window_days = serializers.IntegerField(default=60, required=False)
