"""
Data Center — Django Admin Registration
"""

from django.contrib import admin

from apps.data_center.models import (
    DataProviderSettingsModel,
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
        return not DataProviderSettingsModel.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[override]
        return False
