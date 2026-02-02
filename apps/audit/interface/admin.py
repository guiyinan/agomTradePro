"""
Django Admin for Audit.
"""

from django.contrib import admin
from apps.audit.infrastructure.models import (
    AuditReport,
    AttributionReport,
    LossAnalysis,
    ExperienceSummary
)


@admin.register(AuditReport)
class AuditReportAdmin(admin.ModelAdmin):
    """Admin interface for AuditReport"""

    list_display = [
        'period_start', 'period_end', 'total_pnl',
        'regime_timing_pnl', 'asset_selection_pnl'
    ]
    list_filter = ['period_start', 'period_end']
    date_hierarchy = 'period_start'
    readonly_fields = ['created_at']


@admin.register(AttributionReport)
class AttributionReportAdmin(admin.ModelAdmin):
    """Admin interface for AttributionReport"""

    list_display = [
        'id', 'backtest', 'period_start', 'period_end',
        'total_pnl', 'regime_timing_pnl', 'asset_selection_pnl',
        'regime_accuracy', 'created_at'
    ]
    list_filter = ['period_start', 'period_end', 'regime_predicted', 'created_at']
    search_fields = ['backtest__strategy_name']
    readonly_fields = [
        'regime_timing_pnl', 'asset_selection_pnl', 'interaction_pnl',
        'total_pnl', 'regime_accuracy', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'period_start'


@admin.register(LossAnalysis)
class LossAnalysisAdmin(admin.ModelAdmin):
    """Admin interface for LossAnalysis"""

    list_display = [
        'report', 'loss_source', 'impact', 'impact_percentage', 'created_at'
    ]
    list_filter = ['loss_source', 'created_at']
    search_fields = ['report__backtest__strategy_name', 'description']
    readonly_fields = ['impact_percentage', 'created_at']


@admin.register(ExperienceSummary)
class ExperienceSummaryAdmin(admin.ModelAdmin):
    """Admin interface for ExperienceSummary"""

    list_display = [
        'report', 'priority', 'is_applied', 'applied_at', 'created_at'
    ]
    list_filter = ['priority', 'is_applied', 'applied_at', 'created_at']
    search_fields = ['lesson', 'recommendation', 'report__backtest__strategy_name']
    readonly_fields = ['created_at']
