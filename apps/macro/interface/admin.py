"""
Django Admin configuration for Macro Data.
"""

from django.contrib import admin
from apps.macro.infrastructure.models import MacroIndicator


@admin.register(MacroIndicator)
class MacroIndicatorAdmin(admin.ModelAdmin):
    """Admin interface for MacroIndicator"""

    list_display = ['code', 'value', 'observed_at', 'source', 'revision_number']
    list_filter = ['code', 'source', 'observed_at']
    search_fields = ['code']
    date_hierarchy = 'observed_at'
    readonly_fields = ['created_at', 'updated_at']
