from django.contrib import admin

from apps.pulse.models import (
    NavigatorAssetConfigModel,
    PulseIndicatorConfigModel,
    PulseLog,
)


@admin.register(PulseLog)
class PulseLogAdmin(admin.ModelAdmin):
    list_display = [
        "observed_at",
        "regime_context",
        "composite_score",
        "regime_strength",
        "transition_warning",
        "data_source",
        "created_at",
    ]
    list_filter = ["regime_context", "regime_strength", "transition_warning", "data_source"]
    search_fields = ["regime_context"]
    readonly_fields = ["created_at", "indicator_readings", "transition_reasons"]
    ordering = ["-observed_at"]


@admin.register(PulseIndicatorConfigModel)
class PulseIndicatorConfigAdmin(admin.ModelAdmin):
    list_display = [
        "indicator_code",
        "indicator_name",
        "dimension",
        "frequency",
        "signal_type",
        "weight",
        "is_active",
    ]
    list_filter = ["dimension", "frequency", "signal_type", "is_active"]
    search_fields = ["indicator_code", "indicator_name"]
    list_editable = ["weight", "is_active"]
    ordering = ["dimension", "indicator_code"]


@admin.register(NavigatorAssetConfigModel)
class NavigatorAssetConfigAdmin(admin.ModelAdmin):
    list_display = [
        "regime_name",
        "risk_budget",
        "is_active",
        "updated_at",
    ]
    list_filter = ["regime_name", "is_active"]
    list_editable = ["risk_budget", "is_active"]
    ordering = ["regime_name"]
