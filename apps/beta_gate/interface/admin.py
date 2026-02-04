"""
Beta Gate Django Admin Configuration

硬闸门过滤的 Django Admin 配置。
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from ..infrastructure.models import (
    GateConfigModel,
    GateDecisionModel,
    VisibilityUniverseSnapshotModel,
)


@admin.register(GateConfigModel)
class GateConfigAdmin(admin.ModelAdmin):
    """
    闸门配置 Admin
    """

    list_display = [
        "config_id",
        "risk_profile",
        "version",
        "is_active",
        "effective_date",
        "expires_at",
        "created_at",
        "updated_at",
    ]

    list_filter = [
        "risk_profile",
        "is_active",
        "created_at",
        "effective_date",
    ]

    search_fields = [
        "config_id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "config_id",
                "risk_profile",
                "version",
                "is_active",
            )
        }),
        ("约束配置", {
            "fields": (
                "regime_constraints",
                "policy_constraints",
                "portfolio_constraints",
            ),
            "classes": ("collapse",),
        }),
        ("时间配置", {
            "fields": (
                "effective_date",
                "expires_at",
                "created_at",
                "updated_at",
            )
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        """动态设置只读字段"""
        if obj:  # 编辑时
            return self.readonly_fields + ["config_id", "version"]
        return self.readonly_fields


@admin.register(GateDecisionModel)
class GateDecisionAdmin(admin.ModelAdmin):
    """
    闸门决策 Admin
    """

    list_display = [
        "decision_id",
        "asset_code",
        "asset_class",
        "status",
        "current_regime",
        "policy_level",
        "regime_confidence",
        "evaluated_at",
    ]

    list_filter = [
        "status",
        "current_regime",
        "evaluated_at",
    ]

    search_fields = [
        "decision_id",
        "asset_code",
    ]

    readonly_fields = [
        "decision_id",
        "evaluated_at",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "decision_id",
                "asset_code",
                "asset_class",
                "status",
                "evaluated_at",
            )
        }),
        ("环境信息", {
            "fields": (
                "current_regime",
                "policy_level",
                "regime_confidence",
            )
        }),
        ("评估详情", {
            "fields": (
                "evaluation_details",
            ),
            "classes": ("collapse",),
        }),
    )


@admin.register(VisibilityUniverseSnapshotModel)
class VisibilityUniverseSnapshotAdmin(admin.ModelAdmin):
    """
    可见性宇宙快照 Admin
    """

    list_display = [
        "snapshot_id",
        "current_regime",
        "policy_level",
        "regime_confidence",
        "risk_profile",
        "visible_categories_count",
        "visible_strategies_count",
        "hard_exclusions_count",
        "created_at",
    ]

    list_filter = [
        "current_regime",
        "policy_level",
        "risk_profile",
        "created_at",
    ]

    search_fields = [
        "snapshot_id",
        "regime_snapshot_id",
        "policy_snapshot_id",
    ]

    readonly_fields = [
        "snapshot_id",
        "created_at",
        "visible_asset_categories_display",
        "visible_strategies_display",
        "hard_exclusions_display",
        "watch_list_display",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "snapshot_id",
                "current_regime",
                "policy_level",
                "regime_confidence",
                "risk_profile",
                "created_at",
            )
        }),
        ("快照引用", {
            "fields": (
                "regime_snapshot_id",
                "policy_snapshot_id",
            ),
            "classes": ("collapse",),
        }),
        ("可见性配置", {
            "fields": (
                "visible_asset_categories",
                "visible_asset_categories_display",
                "visible_strategies",
                "visible_strategies_display",
            ),
            "classes": ("collapse",),
        }),
        ("列表配置", {
            "fields": (
                "hard_exclusions",
                "hard_exclusions_display",
                "watch_list",
                "watch_list_display",
            ),
            "classes": ("collapse",),
        }),
    )

    def visible_categories_count(self, obj):
        """可见类别数量"""
        return len(obj.visible_asset_categories)
    visible_categories_count.short_description = "可见类别数"

    def visible_strategies_count(self, obj):
        """可见策略数量"""
        return len(obj.visible_strategies)
    visible_strategies_count.short_description = "可见策略数"

    def hard_exclusions_count(self, obj):
        """硬排除数量"""
        return len(obj.hard_exclusions)
    hard_exclusions_count.short_description = "硬排除数"

    def visible_asset_categories_display(self, obj):
        """显示可见资产类别"""
        if obj.visible_asset_categories:
            return format_html(
                '<ul>{}</ul>',
                ''.join(f'<li>{cat}</li>' for cat in obj.visible_asset_categories)
            )
        return "-"
    visible_asset_categories_display.short_description = "可见资产类别"

    def visible_strategies_display(self, obj):
        """显示可见策略"""
        if obj.visible_strategies:
            return format_html(
                '<ul>{}</ul>',
                ''.join(f'<li>{s}</li>' for s in obj.visible_strategies)
            )
        return "-"
    visible_strategies_display.short_description = "可见策略"

    def hard_exclusions_display(self, obj):
        """显示硬排除列表"""
        if obj.hard_exclusions:
            return format_html(
                '<ul>{}</ul>',
                ''.join(f'<li>{item}</li>' for item in obj.hard_exclusions)
            )
        return "-"
    hard_exclusions_display.short_description = "硬排除列表"

    def watch_list_display(self, obj):
        """显示观察列表"""
        if obj.watch_list:
            return format_html(
                '<ul>{}</ul>',
                ''.join(f'<li>{item}</li>' for item in obj.watch_list)
            )
        return "-"
    watch_list_display.short_description = "观察列表"

    def has_add_permission(self, request):
        """禁止手动添加"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改"""
        return False
