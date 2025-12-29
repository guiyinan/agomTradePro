"""
Django Admin for Backtest.
"""

from django.contrib import admin
from apps.backtest.infrastructure.models import BacktestResult


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    """Admin interface for BacktestResult"""

    list_display = [
        'name', 'start_date', 'end_date', 'total_return',
        'annualized_return', 'max_drawdown', 'sharpe_ratio'
    ]
    list_filter = ['start_date', 'end_date']
    search_fields = ['name']
    date_hierarchy = 'start_date'
    readonly_fields = ['created_at']
