"""
Alpha Trigger Django Admin Configuration

Alpha 事件触发的 Django Admin 配置。
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..infrastructure.models import (
    AlphaCandidateModel,
    AlphaTriggerModel,
)


@admin.register(AlphaTriggerModel)
class AlphaTriggerAdmin(admin.ModelAdmin):
    """
    Alpha 触发器 Admin
    """

    list_display = [
        "trigger_id",
        "trigger_type",
        "asset_code",
        "asset_class",
        "direction",
        "strength_display",
        "confidence",
        "status_display",
        "related_regime",
        "created_at",
        "expires_at",
    ]

    list_filter = [
        "trigger_type",
        "status",
        "strength",
        "direction",
        "created_at",
    ]

    search_fields = [
        "trigger_id",
        "asset_code",
        "source_signal_id",
        "thesis",
    ]

    readonly_fields = [
        "trigger_id",
        "created_at",
        "triggered_at",
        "invalidated_at",
        "invalidation_conditions_display",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "trigger_id",
                "trigger_type",
                "asset_code",
                "asset_class",
                "direction",
                "status",
                "created_at",
            )
        }),
        ("条件配置", {
            "fields": (
                "trigger_condition",
                "invalidation_conditions",
                "invalidation_conditions_display",
            ),
            "classes": ("collapse",),
        }),
        ("信号配置", {
            "fields": (
                "strength",
                "confidence",
                "thesis",
            )
        }),
        ("时间配置", {
            "fields": (
                "triggered_at",
                "invalidated_at",
                "expires_at",
            )
        }),
        ("关联信息", {
            "fields": (
                "source_signal_id",
                "related_regime",
                "related_policy_level",
            ),
            "classes": ("collapse",),
        }),
        ("自定义数据", {
            "fields": ("custom_data",),
            "classes": ("collapse",),
        }),
    )

    def strength_display(self, obj):
        """显示信号强度"""
        colors = {
            "VERY_WEAK": "#ccc",
            "WEAK": "#aaa",
            "MODERATE": "#666",
            "STRONG": "#2ecc71",
            "VERY_STRONG": "#27ae60",
        }
        color = colors.get(obj.strength, "#666")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_strength_display()
        )
    strength_display.short_description = "强度"

    def status_display(self, obj):
        """显示状态"""
        status_colors = {
            "ACTIVE": "#2ecc71",
            "TRIGGERED": "#3498db",
            "INVALIDATED": "#e74c3c",
            "EXPIRED": "#95a5a6",
            "CANCELLED": "#f39c12",
        }
        color = status_colors.get(obj.status, "#666")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = "状态"

    def invalidation_conditions_display(self, obj):
        """显示证伪条件"""
        if obj.invalidation_conditions:
            import json
            conditions = []
            for cond in obj.invalidation_conditions:
                condition_type = cond.get("condition_type", "UNKNOWN")
                indicator = cond.get("indicator_code", "")
                threshold = cond.get("threshold", "")
                conditions.append(f"{condition_type}: {indicator} {threshold}")
            return format_html(
                '<ul>{}</ul>',
                ''.join(f'<li>{c}</li>' for c in conditions)
            )
        return "-"
    invalidation_conditions_display.short_description = "证伪条件"

    def get_readonly_fields(self, request, obj=None):
        """动态设置只读字段"""
        if obj:  # 编辑时
            return self.readonly_fields + ["trigger_type", "asset_code"]
        return self.readonly_fields


@admin.register(AlphaCandidateModel)
class AlphaCandidateAdmin(admin.ModelAdmin):
    """
    Alpha 候选 Admin
    """

    list_display = [
        "candidate_id",
        "trigger_id_link",
        "asset_code",
        "asset_class",
        "direction",
        "strength_display",
        "confidence",
        "status_display",
        "time_horizon",
        "risk_level",
        "created_at",
    ]

    list_filter = [
        "status",
        "strength",
        "risk_level",
        "direction",
        "created_at",
    ]

    search_fields = [
        "candidate_id",
        "trigger_id",
        "asset_code",
        "thesis",
    ]

    readonly_fields = [
        "candidate_id",
        "created_at",
        "updated_at",
        "status_changed_at",
        "promoted_to_signal_at",
        "entry_zone_display",
        "exit_zone_display",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "candidate_id",
                "trigger_id",
                "asset_code",
                "asset_class",
                "direction",
                "status",
                "created_at",
            )
        }),
        ("信号配置", {
            "fields": (
                "strength",
                "confidence",
                "thesis",
            )
        }),
        ("交易配置", {
            "fields": (
                "entry_zone",
                "entry_zone_display",
                "exit_zone",
                "exit_zone_display",
                "time_horizon",
                "expected_return",
                "risk_level",
            ),
            "classes": ("collapse",),
        }),
        ("时间配置", {
            "fields": (
                "updated_at",
                "status_changed_at",
                "promoted_to_signal_at",
            )
        }),
        ("自定义数据", {
            "fields": ("custom_data",),
            "classes": ("collapse",),
        }),
    )

    def trigger_id_link(self, obj):
        """触发器链接"""
        if obj.trigger_id:
            url = reverse(f"admin:{self.model._meta.app_label}_alphatriggermodel_change", args=[obj.trigger_id])
            return format_html('<a href="{}">{}</a>', url, obj.trigger_id)
        return "-"
    trigger_id_link.short_description = "触发器"

    def strength_display(self, obj):
        """显示信号强度"""
        colors = {
            "VERY_WEAK": "#ccc",
            "WEAK": "#aaa",
            "MODERATE": "#666",
            "STRONG": "#2ecc71",
            "VERY_STRONG": "#27ae60",
        }
        color = colors.get(obj.strength, "#666")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_strength_display()
        )
    strength_display.short_description = "强度"

    def status_display(self, obj):
        """显示状态"""
        status_colors = {
            "WATCH": "#f39c12",
            "CANDIDATE": "#3498db",
            "ACTIONABLE": "#2ecc71",
            "EXECUTED": "#9b59b6",
            "CANCELLED": "#e74c3c",
        }
        color = status_colors.get(obj.status, "#666")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = "状态"

    def entry_zone_display(self, obj):
        """显示入场区域"""
        if obj.entry_zone:
            import json
            return format_html(
                '<pre>{}</pre>',
                json.dumps(obj.entry_zone, indent=2, ensure_ascii=False)
            )
        return "-"
    entry_zone_display.short_description = "入场区域"

    def exit_zone_display(self, obj):
        """显示出场区域"""
        if obj.exit_zone:
            import json
            return format_html(
                '<pre>{}</pre>',
                json.dumps(obj.exit_zone, indent=2, ensure_ascii=False)
            )
        return "-"
    exit_zone_display.short_description = "出场区域"

    def has_add_permission(self, request):
        """禁止手动添加"""
        return False

    def get_readonly_fields(self, request, obj=None):
        """动态设置只读字段"""
        if obj:  # 编辑时，允许修改状态
            readonly = list(self.readonly_fields)
            if "status" in readonly:
                readonly.remove("status")
            return readonly
        return self.readonly_fields
