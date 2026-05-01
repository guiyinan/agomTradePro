"""
Data Center — Django Admin Registration
"""

from django.contrib import admin

from apps.data_center.application.interface_services import can_create_provider_settings
from apps.data_center.models import (
    DataProviderSettingsModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    ProviderConfigModel,
)


@admin.register(ProviderConfigModel)
class ProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "is_active", "priority", "updated_at")
    list_filter = ("source_type", "is_active")
    search_fields = ("name", "description")
    ordering = ("priority", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Identity", {"fields": ("name", "source_type", "is_active", "priority")}),
        (
            "Credentials",
            {
                "fields": ("api_key", "api_secret", "http_url", "api_endpoint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Advanced",
            {
                "fields": ("extra_config", "description"),
                "classes": ("collapse",),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(DataProviderSettingsModel)
class DataProviderSettingsAdmin(admin.ModelAdmin):
    list_display = ("default_source", "enable_failover", "failover_tolerance", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request) -> bool:  # type: ignore[override]
        """Only one singleton row is allowed."""
        return can_create_provider_settings()

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[override]
        return False


@admin.register(IndicatorCatalogModel)
class IndicatorCatalogAdmin(admin.ModelAdmin):
    list_display = ("code", "name_cn", "category", "default_period_type", "is_active")
    list_filter = ("category", "default_period_type", "is_active")
    search_fields = ("code", "name_cn", "name_en", "description")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(IndicatorUnitRuleModel)
class IndicatorUnitRuleAdmin(admin.ModelAdmin):
    list_display = (
        "indicator_code",
        "source_type",
        "original_unit",
        "storage_unit",
        "display_unit",
        "dimension_key",
        "priority",
        "is_active",
    )
    list_filter = ("source_type", "dimension_key", "is_active")
    search_fields = ("indicator_code", "original_unit", "storage_unit", "display_unit")
    ordering = ("indicator_code", "-priority", "source_type", "original_unit")
    readonly_fields = ("created_at", "updated_at")
