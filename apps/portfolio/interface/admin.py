"""Admin management for versioned portfolio planning policies."""

from django.contrib import admin

from apps.portfolio.models import PortfolioPlanningPolicyModel


@admin.register(PortfolioPlanningPolicyModel)
class PortfolioPlanningPolicyAdmin(admin.ModelAdmin):
    """Expose policy versions while preserving immutable thresholds."""

    list_display = ("version", "status", "buy_lot_size", "created_at")
    list_filter = ("status",)
    search_fields = ("version",)
    readonly_fields = ("created_at",)
