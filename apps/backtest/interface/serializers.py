"""
DRF Serializers for Backtest Module.
"""

from rest_framework import serializers
from datetime import date
from typing import Optional

from ..infrastructure.models import BacktestResultModel, BacktestTradeModel


class BacktestConfigSerializer(serializers.Serializer):
    """回测配置序列化器"""
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = serializers.FloatField(min_value=0)
    rebalance_frequency = serializers.ChoiceField(
        choices=['monthly', 'quarterly', 'yearly'],
        default='monthly'
    )
    use_pit_data = serializers.BooleanField(default=False)
    transaction_cost_bps = serializers.FloatField(min_value=0, default=10.0)

    def validate(self, data):
        """验证配置"""
        if data['start_date'] >= data['end_date']:
            raise serializers.ValidationError("start_date must be before end_date")
        return data


class BacktestResultSerializer(serializers.ModelSerializer):
    """回测结果序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BacktestResultModel
        fields = [
            'id',
            'name',
            'status',
            'status_display',
            'start_date',
            'end_date',
            'initial_capital',
            'final_capital',
            'total_return',
            'annualized_return',
            'max_drawdown',
            'sharpe_ratio',
            'rebalance_frequency',
            'use_pit_data',
            'transaction_cost_bps',
            'equity_curve',
            'regime_history',
            'trades',
            'warnings',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'final_capital',
            'total_return',
            'annualized_return',
            'max_drawdown',
            'sharpe_ratio',
            'equity_curve',
            'regime_history',
            'trades',
            'warnings',
            'error_message',
            'created_at',
            'updated_at',
            'completed_at',
        ]


class BacktestListSerializer(serializers.ModelSerializer):
    """回测列表序列化器（精简版）"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BacktestResultModel
        fields = [
            'id',
            'name',
            'status',
            'status_display',
            'start_date',
            'end_date',
            'total_return',
            'annualized_return',
            'created_at',
        ]


class RunBacktestSerializer(serializers.Serializer):
    """运行回测请求序列化器"""
    name = serializers.CharField(max_length=200)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = serializers.FloatField(min_value=0)
    rebalance_frequency = serializers.ChoiceField(
        choices=['monthly', 'quarterly', 'yearly'],
        default='monthly'
    )
    use_pit_data = serializers.BooleanField(default=False)
    transaction_cost_bps = serializers.FloatField(min_value=0, default=10.0)
    run_async = serializers.BooleanField(default=False)

    def validate(self, data):
        """验证请求"""
        if data['start_date'] >= data['end_date']:
            raise serializers.ValidationError("start_date must be before end_date")
        return data


class BacktestStatisticsSerializer(serializers.Serializer):
    """回测统计序列化器"""
    total = serializers.IntegerField()
    by_status = serializers.DictField()
    avg_return = serializers.FloatField()
    max_return = serializers.FloatField()
    min_return = serializers.FloatField()


class TradeSerializer(serializers.ModelSerializer):
    """交易记录序列化器"""
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = BacktestTradeModel
        fields = [
            'id',
            'backtest',
            'trade_date',
            'asset_class',
            'action',
            'action_display',
            'shares',
            'price',
            'notional',
            'cost',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']
