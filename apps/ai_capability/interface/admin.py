"""
AI Capability Catalog Admin Configuration.
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.ai_capability.models import (
    CapabilityCatalogModel,
    CapabilityRoutingLogModel,
    CapabilitySyncLogModel,
)


@admin.register(CapabilityCatalogModel)
class CapabilityCatalogAdmin(admin.ModelAdmin):
    """Admin for capability catalog."""

    list_display = [
        "capability_key",
        "name",
        "source_type",
        "route_group",
        "risk_level",
        "enabled_for_routing",
        "review_status",
        "priority_weight",
    ]
    list_filter = [
        "source_type",
        "route_group",
        "risk_level",
        "enabled_for_routing",
        "review_status",
        "visibility",
        "auto_collected",
    ]
    search_fields = ["capability_key", "name", "summary", "description"]
    readonly_fields = ["created_at", "updated_at", "last_synced_at"]

    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "capability_key",
                    "source_type",
                    "source_ref",
                    "name",
                    "summary",
                    "description",
                    "category",
                ),
            },
        ),
        (
            "Classification",
            {
                "fields": (
                    "route_group",
                    "risk_level",
                    "tags",
                ),
            },
        ),
        (
            "Usage Guidance",
            {
                "fields": (
                    "when_to_use",
                    "when_not_to_use",
                    "examples",
                ),
            },
        ),
        (
            "Input Schema",
            {
                "fields": ("input_schema",),
                "classes": ("collapse",),
            },
        ),
        (
            "Execution Config",
            {
                "fields": (
                    "execution_kind",
                    "execution_target",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Routing Control",
            {
                "fields": (
                    "requires_mcp",
                    "requires_confirmation",
                    "enabled_for_routing",
                    "enabled_for_terminal",
                    "enabled_for_chat",
                    "enabled_for_agent",
                ),
            },
        ),
        (
            "Visibility & Review",
            {
                "fields": (
                    "visibility",
                    "auto_collected",
                    "review_status",
                    "priority_weight",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "last_synced_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def colored_risk_level(self, obj):
        colors = {
            "safe": "green",
            "low": "blue",
            "medium": "orange",
            "high": "red",
            "critical": "darkred",
        }
        color = colors.get(obj.risk_level, "gray")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_risk_level_display(),
        )

    colored_risk_level.short_description = "Risk Level"


@admin.register(CapabilityRoutingLogModel)
class CapabilityRoutingLogAdmin(admin.ModelAdmin):
    """Admin for routing logs."""

    list_display = [
        "created_at",
        "entrypoint",
        "decision",
        "selected_capability_key",
        "confidence",
        "session_id",
    ]
    list_filter = ["entrypoint", "decision", "created_at"]
    search_fields = ["raw_message", "session_id", "selected_capability_key"]
    readonly_fields = [
        "entrypoint",
        "user",
        "session_id",
        "raw_message",
        "retrieved_candidates",
        "selected_capability_key",
        "confidence",
        "decision",
        "fallback_reason",
        "execution_result",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CapabilitySyncLogModel)
class CapabilitySyncLogAdmin(admin.ModelAdmin):
    """Admin for sync logs."""

    list_display = [
        "started_at",
        "sync_type",
        "total_discovered",
        "created_count",
        "updated_count",
        "disabled_count",
        "error_count",
    ]
    list_filter = ["sync_type", "started_at"]
    readonly_fields = [
        "sync_type",
        "started_at",
        "finished_at",
        "total_discovered",
        "created_count",
        "updated_count",
        "disabled_count",
        "error_count",
        "summary_payload",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
