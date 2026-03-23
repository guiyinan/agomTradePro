"""
Django Admin for Backtest.
"""

from django.contrib import admin

from ..infrastructure.models import BacktestResultModel, BacktestTradeModel


@admin.register(BacktestResultModel)
class BacktestResultAdmin(admin.ModelAdmin):
    """Admin interface for BacktestResult"""

    list_display = [
        'id', 'name', 'status', 'start_date', 'end_date',
        'total_return', 'annualized_return', 'max_drawdown', 'sharpe_ratio',
        'created_at', 'completed_at'
    ]
    list_filter = ['status', 'start_date', 'end_date', 'rebalance_frequency']
    search_fields = ['name']
    date_hierarchy = 'start_date'
    readonly_fields = [
        'created_at', 'updated_at', 'completed_at',
        'final_capital', 'total_return', 'annualized_return',
        'max_drawdown', 'sharpe_ratio', 'equity_curve',
        'regime_history', 'trades', 'warnings'
    ]

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'status', 'error_message')
        }),
        ('回测配置', {
            'fields': (
                'start_date', 'end_date', 'initial_capital',
                'rebalance_frequency', 'use_pit_data', 'transaction_cost_bps'
            )
        }),
        ('回测结果', {
            'fields': (
                'final_capital', 'total_return', 'annualized_return',
                'max_drawdown', 'sharpe_ratio'
            )
        }),
        ('详细数据', {
            'fields': ('equity_curve', 'regime_history', 'trades', 'warnings'),
            'classes': ('collapse',)
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        # 禁止手动添加，通过 API 创建
        return False

    def has_change_permission(self, request, obj=None):
        # 只允许修改状态
        return False


@admin.register(BacktestTradeModel)
class BacktestTradeAdmin(admin.ModelAdmin):
    """Admin interface for BacktestTrade"""

    list_display = [
        'id', 'backtest', 'trade_date', 'asset_class', 'action',
        'shares', 'price', 'notional', 'cost'
    ]
    list_filter = ['action', 'asset_class', 'trade_date']
    search_fields = ['backtest__name', 'asset_class']
    date_hierarchy = 'trade_date'
    readonly_fields = ['created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

