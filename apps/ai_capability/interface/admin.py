"""
AI Capability Catalog Admin Configuration.
"""

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html

from apps.ai_capability.models import (
    CapabilityCatalogModel,
    CapabilityRoutingLogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
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
        "semantic_key",
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
    search_fields = [
        "capability_key",
        "semantic_key",
        "collected_semantic_key",
        "name",
        "summary",
        "description",
    ]
    readonly_fields = [
        "collected_semantic_key",
        "created_at",
        "updated_at",
        "last_synced_at",
    ]

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
                    "collected_semantic_key",
                    "semantic_key",
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

    def colored_risk_level(self, obj: CapabilityCatalogModel) -> str:
        """Render the risk level with a compact severity color."""

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

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Keep routing logs append-only from the admin interface."""

        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CapabilityRoutingLogModel | None = None,
    ) -> bool:
        """Keep routing logs immutable from the admin interface."""

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

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Keep sync logs append-only from the admin interface."""

        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CapabilitySyncLogModel | None = None,
    ) -> bool:
        """Keep sync logs immutable from the admin interface."""

        return False


@admin.register(CapabilitySemanticOverrideModel)
class CapabilitySemanticOverrideAdmin(admin.ModelAdmin):
    """Read-only current semantic override projection."""

    list_display = [
        "capability_key",
        "semantic_key",
        "is_active",
        "updated_by",
        "updated_at",
    ]
    list_filter = ["is_active", "updated_at"]
    search_fields = ["capability_key", "semantic_key", "reason"]
    readonly_fields = [
        "capability_key",
        "semantic_key",
        "reason",
        "is_active",
        "updated_by",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require the audited operator workflow for creation."""

        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CapabilitySemanticOverrideModel | None = None,
    ) -> bool:
        """Require the audited operator workflow for changes."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CapabilitySemanticOverrideModel | None = None,
    ) -> bool:
        """Preserve current-decision history for audited removal."""

        return False


@admin.register(CapabilitySemanticAuditModel)
class CapabilitySemanticAuditAdmin(admin.ModelAdmin):
    """Immutable semantic governance audit history."""

    list_display = [
        "created_at",
        "capability_key",
        "action",
        "operator",
        "idempotency_key",
    ]
    list_filter = ["action", "created_at"]
    search_fields = [
        "capability_key",
        "old_collected_value",
        "old_effective_value",
        "new_effective_value",
        "idempotency_key",
        "reason",
        "request_fingerprint",
    ]
    readonly_fields = [
        "batch_id",
        "idempotency_key",
        "capability_key",
        "action",
        "old_collected_value",
        "old_effective_value",
        "new_effective_value",
        "reason",
        "operator",
        "request_fingerprint",
        "created_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Audit evidence can only be created transactionally."""

        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CapabilitySemanticAuditModel | None = None,
    ) -> bool:
        """Audit evidence is append-only."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CapabilitySemanticAuditModel | None = None,
    ) -> bool:
        """Audit evidence is immutable."""

        return False
