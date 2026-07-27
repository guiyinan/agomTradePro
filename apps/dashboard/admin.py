"""Canonical typed Django Admin registrations for Dashboard models."""

from __future__ import annotations

import json

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import SafeString

from apps.dashboard.infrastructure.models import (
    DashboardAlertModel,
    DashboardCardModel,
    DashboardConfigModel,
    DashboardSnapshotModel,
    DashboardUserConfigModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(DashboardConfigModel)
class DashboardConfigAdmin(TypedModelAdmin[DashboardConfigModel]):
    """Manage shared Dashboard configurations."""

    list_display = ["config_id", "name", "is_default", "is_active", "created_at", "updated_at"]
    list_filter = ["is_default", "is_active", "created_at"]
    search_fields = ["config_id", "name", "description"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("基本信息", {"fields": ("config_id", "name", "description", "is_default", "is_active")}),
        ("配置", {"fields": ("layout_config", "card_configs")}),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(DashboardUserConfigModel)
class DashboardUserConfigAdmin(TypedModelAdmin[DashboardUserConfigModel]):
    """Manage user-specific Dashboard presentation settings."""

    list_display = [
        "user",
        "dashboard_config",
        "theme",
        "refresh_enabled",
        "refresh_interval",
        "last_updated",
    ]
    list_filter = ["theme", "refresh_enabled", "last_updated"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["last_updated"]
    fieldsets = (
        ("基本信息", {"fields": ("user", "dashboard_config")}),
        ("显示设置", {"fields": ("hidden_cards", "collapsed_cards", "card_order", "theme")}),
        ("刷新设置", {"fields": ("refresh_enabled", "refresh_interval")}),
        ("自定义配置", {"fields": ("custom_card_config",), "classes": ("collapse",)}),
        ("元数据", {"fields": ("last_updated",), "classes": ("collapse",)}),
    )


@admin.register(DashboardCardModel)
class DashboardCardAdmin(TypedModelAdmin[DashboardCardModel]):
    """Manage Dashboard card definitions and layout metadata."""

    list_display = ["card_id", "card_type", "title", "is_visible", "display_order", "created_at"]
    list_filter = ["card_type", "is_visible", "is_collapsible", "is_draggable", "created_at"]
    search_fields = ["card_id", "title", "description"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        ("基本信息", {"fields": ("card_id", "card_type", "title", "description")}),
        ("组件配置", {"fields": ("widget_config", "data_source")}),
        (
            "可见性",
            {
                "fields": (
                    "visibility_conditions",
                    "is_visible",
                    "is_collapsible",
                    "is_draggable",
                    "is_resizable",
                )
            },
        ),
        ("布局", {"fields": ("position", "size", "display_order")}),
        ("依赖", {"fields": ("dependencies",), "classes": ("collapse",)}),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(DashboardAlertModel)
class DashboardAlertAdmin(TypedModelAdmin[DashboardAlertModel]):
    """Manage Dashboard alert rules and inspect trigger state."""

    list_display = [
        "alert_id",
        "name",
        "metric",
        "severity_badge",
        "threshold",
        "is_enabled",
        "last_triggered_at",
        "trigger_count",
    ]
    list_filter = ["severity", "is_enabled", "last_triggered_at"]
    search_fields = ["alert_id", "name", "description", "metric"]
    readonly_fields = ["created_at", "updated_at", "last_triggered_at", "trigger_count"]
    fieldsets = (
        ("基本信息", {"fields": ("alert_id", "name", "description", "is_enabled")}),
        ("告警条件", {"fields": ("metric", "condition", "severity", "threshold")}),
        ("通知", {"fields": ("notification_channels",)}),
        ("冷却设置", {"fields": ("cooldown",)}),
        (
            "统计",
            {"fields": ("last_triggered_at", "trigger_count"), "classes": ("collapse",)},
        ),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="严重级别", ordering="severity")
    def severity_badge(self, obj: DashboardAlertModel) -> SafeString:
        """Render the governed severity label without dynamic Admin metadata."""

        colors = {
            "info": "#3498db",
            "warning": "#f39c12",
            "error": "#e74c3c",
            "critical": "#8e44ad",
        }
        color = colors.get(obj.severity, "#95a5a6")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 3px;">{}</span>',
            color,
            obj.get_severity_display(),
        )


@admin.register(DashboardSnapshotModel)
class DashboardSnapshotAdmin(TypedModelAdmin[DashboardSnapshotModel]):
    """Expose immutable Dashboard snapshots for operational inspection."""

    list_display = ["user", "captured_at", "snapshot_size"]
    list_filter = ["captured_at"]
    search_fields = ["user__username"]
    readonly_fields = ["user", "snapshot_data", "captured_at"]
    fieldsets = (
        ("基本信息", {"fields": ("user", "captured_at")}),
        ("快照数据", {"fields": ("snapshot_data",), "classes": ("collapse",)}),
    )

    @admin.display(description="快照大小")
    def snapshot_size(self, obj: DashboardSnapshotModel) -> str:
        """Return the serialized JSON snapshot size for operator inspection."""

        size = len(json.dumps(obj.snapshot_data))
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating system snapshots."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: DashboardSnapshotModel | None = None,
    ) -> bool:
        """Keep captured snapshots immutable in Admin."""

        del request, obj
        return False
