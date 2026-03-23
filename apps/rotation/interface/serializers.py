"""
Rotation Module Interface Layer - Serializers

DRF Serializers for the rotation module API.
"""

from rest_framework import serializers

from apps.rotation.infrastructure.models import (
    AssetClassModel,
    MomentumScoreModel,
    PortfolioRotationConfigModel,
    RotationConfigModel,
    RotationPortfolioModel,
    RotationSignalModel,
    RotationTemplateModel,
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


class RotationTemplateSerializer(serializers.ModelSerializer):
    """Serializer for RotationTemplate (read-only presets from DB)"""
    allocations = serializers.JSONField(source='regime_allocations', read_only=True)

    class Meta:
        model = RotationTemplateModel
        fields = ['id', 'key', 'name', 'description', 'regime_allocations', 'allocations', 'display_order']


class PortfolioRotationConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for per-account rotation config.

    MCP and frontend both use this to read/write per-account regime allocations
    and risk tolerance. Validates that each regime's weights sum to 1.0.
    """
    account_name = serializers.CharField(source='account.account_name', read_only=True)
    account_type = serializers.CharField(source='account.account_type', read_only=True)
    base_config_name = serializers.CharField(source='base_config.name', read_only=True, default=None)

    class Meta:
        model = PortfolioRotationConfigModel
        fields = [
            'id', 'account', 'account_name', 'account_type',
            'base_config', 'base_config_name',
            'risk_tolerance', 'regime_allocations',
            'is_enabled', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_regime_allocations(self, value: dict) -> dict:
        """Each regime's weights must sum to 1.0 (±0.01 tolerance)."""
        for regime, allocations in value.items():
            if not isinstance(allocations, dict):
                raise serializers.ValidationError(
                    f"象限 {regime} 的配置必须是 dict，收到 {type(allocations).__name__}"
                )
            total = sum(allocations.values())
            if abs(total - 1.0) > 0.01:
                raise serializers.ValidationError(
                    f"象限 {regime} 的权重之和为 {total:.4f}，必须为 1.0（允许 ±0.01 误差）"
                )
        return value
