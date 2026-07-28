"""
AI Capability Catalog Admin Configuration.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import SafeString

from apps.ai_capability.models import (
    CapabilityCatalogModel,
    CapabilityRoutingLogModel,
    CapabilitySemanticAuditModel,
    CapabilitySemanticOverrideModel,
    CapabilitySyncLogModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin

CapabilityEvidenceModelT = TypeVar("CapabilityEvidenceModelT", bound=Model)


class ImmutableCapabilityEvidenceAdmin(
    TypedModelAdmin[CapabilityEvidenceModelT],
    Generic[CapabilityEvidenceModelT],
):
    """Expose generated capability evidence without mutation controls."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating capability evidence."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CapabilityEvidenceModelT | None = None,
    ) -> bool:
        """Keep generated capability evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CapabilityEvidenceModelT | None = None,
    ) -> bool:
        """Require governed retention instead of ad-hoc Admin deletion."""

        del request, obj
        return False


@admin.register(CapabilityCatalogModel)
class CapabilityCatalogAdmin(TypedModelAdmin[CapabilityCatalogModel]):
    """Admin for capability catalog."""

    list_display = [
        "capability_key",
        "name",
        "source_type",
        "route_group",
        "semantic_key",
        "colored_risk_level",
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
        "semantic_key",
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

    @admin.display(description="Risk Level", ordering="risk_level")
    def colored_risk_level(self, obj: CapabilityCatalogModel) -> SafeString:
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

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CapabilityCatalogModel | None = None,
    ) -> bool:
        """Route catalog retirement through synchronization and governance."""

        del request, obj
        return False


@admin.register(CapabilityRoutingLogModel)
class CapabilityRoutingLogAdmin(ImmutableCapabilityEvidenceAdmin[CapabilityRoutingLogModel]):
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
    readonly_fields = [field.name for field in CapabilityRoutingLogModel._meta.fields]


@admin.register(CapabilitySyncLogModel)
class CapabilitySyncLogAdmin(ImmutableCapabilityEvidenceAdmin[CapabilitySyncLogModel]):
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
    readonly_fields = [field.name for field in CapabilitySyncLogModel._meta.fields]


@admin.register(CapabilitySemanticOverrideModel)
class CapabilitySemanticOverrideAdmin(
    ImmutableCapabilityEvidenceAdmin[CapabilitySemanticOverrideModel]
):
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
    readonly_fields = [field.name for field in CapabilitySemanticOverrideModel._meta.fields]


@admin.register(CapabilitySemanticAuditModel)
class CapabilitySemanticAuditAdmin(ImmutableCapabilityEvidenceAdmin[CapabilitySemanticAuditModel]):
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
    readonly_fields = [field.name for field in CapabilitySemanticAuditModel._meta.fields]
