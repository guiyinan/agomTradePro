"""
Django Admin for Audit.
"""

from django.contrib import admin
from apps.audit.infrastructure.models import AuditReport


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
