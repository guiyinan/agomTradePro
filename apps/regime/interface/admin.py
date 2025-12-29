"""
Django Admin for Regime.
"""

from django.contrib import admin
from apps.regime.infrastructure.models import RegimeLog


@admin.register(RegimeLog)
class RegimeLogAdmin(admin.ModelAdmin):
    """Admin interface for RegimeLog"""

    list_display = ['observed_at', 'dominant_regime', 'confidence', 'growth_momentum_z', 'inflation_momentum_z']
    list_filter = ['dominant_regime', 'observed_at']
    date_hierarchy = 'observed_at'
    readonly_fields = ['created_at']
