"""
Decision Rhythm Django Admin Configuration

决策频率约束和配额管理的 Django Admin 配置。
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from ..infrastructure.models import (
    DecisionQuotaModel,
    CooldownPeriodModel,
    DecisionRequestModel,
)


@admin.register(DecisionQuotaModel)
class DecisionQuotaAdmin(admin.ModelAdmin):
    """
    决策配额 Admin
    """

    list_display = [
        "quota_id",
        "period",
        "asset_class_display",
        "priority",
        "usage_display",
        "reset_at",
        "created_at",
    ]

    list_filter = [
        "period",
        "priority",
        "created_at",
    ]

    search_fields = [
        "quota_id",
        "asset_class",
    ]

    readonly_fields = [
        "quota_id",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "quota_id",
                "period",
                "asset_class",
                "priority",
            )
        }),
        ("配额配置", {
            "fields": (
                "max_decisions",
                "used_decisions",
                "reset_at",
            )
        }),
        ("时间信息", {
            "fields": (
                "created_at",
                "updated_at",
            )
        }),
    )

    def asset_class_display(self, obj):
        """显示资产类别"""
        return obj.asset_class or "全局"
    asset_class_display.short_description = "资产类别"

    def usage_display(self, obj):
        """显示使用情况"""
        if obj.max_decisions > 0:
            usage_rate = obj.used_decisions / obj.max_decisions
            remaining = obj.max_decisions - obj.used_decisions

            # 根据使用率设置颜色
            if usage_rate >= 0.9:
                color = "#e74c3c"  # 红色
            elif usage_rate >= 0.7:
                color = "#f39c12"  # 橙色
            else:
                color = "#2ecc71"  # 绿色

            return format_html(
                '<div style="width: 100px; background: #eee; border-radius: 4px;">'
                '<div style="width: {}%; background: {}; height: 20px; border-radius: 4px; '
                'display: flex; align-items: center; justify-content: center; '
                'color: white; font-size: 11px;">{} / {}</div>'
                '</div>',
                usage_rate * 100,
                color,
                obj.used_decisions,
                obj.max_decisions
            )
        return "-"
    usage_display.short_description = "使用情况"


@admin.register(CooldownPeriodModel)
class CooldownPeriodAdmin(admin.ModelAdmin):
    """
    冷却期 Admin
    """

    list_display = [
        "cooldown_id",
        "asset_code",
        "asset_class",
        "direction_display",
        "cooldown_hours",
        "cooldown_end_at",
        "is_active_display",
        "remaining_hours_display",
        "created_at",
    ]

    list_filter = [
        "direction",
        "created_at",
    ]

    search_fields = [
        "cooldown_id",
        "asset_code",
        "decision_request_id",
    ]

    readonly_fields = [
        "cooldown_id",
        "created_at",
        "is_active_display",
        "remaining_hours_display",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "cooldown_id",
                "asset_code",
                "asset_class",
                "direction",
                "created_at",
            )
        }),
        ("冷却配置", {
            "fields": (
                "cooldown_hours",
                "cooldown_end_at",
                "is_active_display",
                "remaining_hours_display",
            )
        }),
        ("关联信息", {
            "fields": ("decision_request_id",),
        }),
    )

    def direction_display(self, obj):
        """显示方向"""
        icons = {
            "BUY": "🟢",
            "SELL": "🔴",
            "BOTH": "🔵",
        }
        icon = icons.get(obj.direction, "")
        return format_html("{} {}", icon, obj.get_direction_display())
    direction_display.short_description = "方向"

    def is_active_display(self, obj):
        """显示是否活跃"""
        from django.utils import timezone

        is_active = obj.cooldown_end_at > timezone.now()
        if is_active:
            return format_html('<span style="color: green;">✓ 活跃</span>')
        else:
            return format_html('<span style="color: gray;">✗ 已过期</span>')
    is_active_display.short_description = "状态"

    def remaining_hours_display(self, obj):
        """显示剩余小时数"""
        from django.utils import timezone

        remaining = (obj.cooldown_end_at - timezone.now()).total_seconds() / 3600
        if remaining > 0:
            return format_html('<span style="color: orange;">{:.1f} 小时</span>', remaining)
        else:
            return format_html('<span style="color: gray;">0 小时</span>')
    remaining_hours_display.short_description = "剩余时间"

    def has_add_permission(self, request):
        """禁止手动添加"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改"""
        return False


@admin.register(DecisionRequestModel)
class DecisionRequestAdmin(admin.ModelAdmin):
    """
    决策请求 Admin
    """

    list_display = [
        "request_id",
        "asset_code",
        "asset_class",
        "direction_display",
        "priority_display",
        "status_display",
        "created_at",
        "processed_at",
    ]

    list_filter = [
        "status",
        "approved",
        "priority",
        "direction",
        "created_at",
    ]

    search_fields = [
        "request_id",
        "asset_code",
        "trigger_id",
        "reason",
    ]

    readonly_fields = [
        "request_id",
        "created_at",
        "processed_at",
    ]

    fieldsets = (
        ("基本信息", {
            "fields": (
                "request_id",
                "asset_code",
                "asset_class",
                "direction",
                "priority",
                "status",
                "created_at",
            )
        }),
        ("决策详情", {
            "fields": (
                "quantity",
                "notional",
                "expected_confidence",
            )
        }),
        ("决策结果", {
            "fields": (
                "approved",
                "approval_reason",
                "rejection_reason",
            )
        }),
        ("关联信息", {
            "fields": (
                "trigger_id",
                "reason",
            )
        }),
        ("时间信息", {
            "fields": ("processed_at",),
        }),
    )

    def direction_display(self, obj):
        """显示方向"""
        icons = {
            "BUY": "🟢",
            "SELL": "🔴",
        }
        icon = icons.get(obj.direction, "")
        return format_html("{} {}", icon, obj.get_direction_display())
    direction_display.short_description = "方向"

    def priority_display(self, obj):
        """显示优先级"""
        colors = {
            "LOW": "#95a5a6",
            "MEDIUM": "#f39c12",
            "HIGH": "#e67e22",
            "URGENT": "#e74c3c",
        }
        color = colors.get(obj.priority, "#666")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_priority_display()
        )
    priority_display.short_description = "优先级"

    def status_display(self, obj):
        """显示状态"""
        if obj.approved:
            return format_html('<span style="color: green;">✓ 批准</span>')
        else:
            return format_html('<span style="color: red;">✗ 拒绝</span>')
    status_display.short_description = "状态"

    def has_add_permission(self, request):
        """禁止手动添加"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改"""
        return False
