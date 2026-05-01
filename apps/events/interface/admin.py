"""
Events Interface Admin

事件 Django Admin 配置。
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.events.application.interface_services import (
    count_related_events_by_correlation_ids,
)
from apps.events.event_store import (
    EventSnapshotModel,
    EventSubscriptionModel,
    StoredEventModel,
)


class StoredEventAdmin(admin.ModelAdmin):
    """存储事件 Admin"""

    list_display = [
        "event_id",
        "event_type",
        "occurred_at",
        "created_at",
        "version",
        "payload_preview",
    ]
    list_filter = ["event_type", "occurred_at", "created_at", "version"]
    search_fields = ["event_id", "event_type", "correlation_id", "causation_id"]
    readonly_fields = [
        "event_id",
        "event_type",
        "occurred_at",
        "created_at",
        "version",
        "payload_display",
        "metadata_display",
    ]

    fieldsets = (
        ("基本信息", {"fields": ("event_id", "event_type", "version")}),
        ("事件数据", {"fields": ("payload_display", "metadata_display")}),
        ("追踪信息", {"fields": ("correlation_id", "causation_id")}),
        ("时间", {"fields": ("occurred_at", "created_at")}),
    )

    def payload_preview(self, obj):
        """显示 payload 预览"""
        import json

        payload_str = json.dumps(obj.payload, ensure_ascii=False)
        if len(payload_str) > 50:
            return payload_str[:50] + "..."
        return payload_str

    payload_preview.short_description = "Payload"

    def payload_display(self, obj):
        """格式化显示 payload"""
        import json

        return format_html(
            '<pre style="white-space: pre-wrap; word-break: break-all;">{}</pre>',
            json.dumps(obj.payload, indent=2, ensure_ascii=False),
        )

    payload_display.short_description = "Payload"

    def metadata_display(self, obj):
        """格式化显示 metadata"""
        import json

        if not obj.metadata:
            return "-"
        return format_html(
            '<pre style="white-space: pre-wrap; word-break: break-all;">{}</pre>',
            json.dumps(obj.metadata, indent=2, ensure_ascii=False),
        )

    metadata_display.short_description = "Metadata"

    def has_add_permission(self, request):
        """禁止手动添加事件"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改事件"""
        return False


@admin.register(EventSnapshotModel)
class EventSnapshotAdmin(admin.ModelAdmin):
    """事件快照 Admin"""

    list_display = [
        "snapshot_id",
        "aggregate_type",
        "aggregate_id",
        "version",
        "created_at",
        "state_size",
    ]
    list_filter = ["aggregate_type", "created_at", "version"]
    search_fields = ["snapshot_id", "aggregate_type", "aggregate_id"]
    readonly_fields = [
        "snapshot_id",
        "aggregate_type",
        "aggregate_id",
        "version",
        "state_display",
        "created_at",
    ]

    fieldsets = (
        ("基本信息", {"fields": ("snapshot_id", "aggregate_type", "aggregate_id", "version")}),
        ("快照数据", {"fields": ("state_display",)}),
        ("时间", {"fields": ("created_at",)}),
    )

    def state_size(self, obj):
        """显示快照大小"""
        import json

        size = len(json.dumps(obj.state))
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"

    state_size.short_description = "大小"

    def state_display(self, obj):
        """格式化显示 state"""
        import json

        return format_html(
            '<pre style="white-space: pre-wrap; word-break: break-all;">{}</pre>',
            json.dumps(obj.state, indent=2, ensure_ascii=False),
        )

    state_display.short_description = "State"

    def has_add_permission(self, request):
        """禁止手动添加快照"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改快照"""
        return False


@admin.register(EventSubscriptionModel)
class EventSubscriptionAdmin(admin.ModelAdmin):
    """事件订阅 Admin"""

    list_display = [
        "subscription_id",
        "handler_id",
        "event_types_display",
        "is_active",
        "created_at",
        "updated_at",
    ]
    list_filter = ["is_active", "created_at", "updated_at"]
    search_fields = ["subscription_id", "handler_id"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("基本信息", {"fields": ("subscription_id", "handler_id", "is_active")}),
        ("订阅配置", {"fields": ("event_types",)}),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def event_types_display(self, obj):
        """显示订阅的事件类型"""
        if not obj.event_types:
            return "-"
        return ", ".join(obj.event_types)

    event_types_display.short_description = "事件类型"


# ========== 自定义 Admin 操作 ==========


@admin.register(StoredEventModel)
class StoredEventActionsAdmin(StoredEventAdmin):
    """带操作的事件 Admin"""

    actions = ["view_correlation_chain", "cleanup_old_events"]

    def view_correlation_chain(self, request, queryset):
        """
        查看关联事件链

        显示与选中事件具有相同 correlation_id 的事件。
        """
        correlation_ids = set(
            queryset.filter(correlation_id__isnull=False).values_list("correlation_id", flat=True)
        )

        if not correlation_ids:
            self.message_user(request, "选中的事件没有关联 ID")
            return

        # 显示结果
        self.message_user(
            request,
            f"找到 {count_related_events_by_correlation_ids(correlation_ids)} 个相关事件"
            f"（{len(correlation_ids)} 个关联链）",
        )

        # 这里可以重定向到自定义视图或直接显示
        # 简化处理：只显示消息

    view_correlation_chain.short_description = "查看关联事件链"

    def cleanup_old_events(self, request, queryset):
        """
        清理旧事件

        删除选中的旧事件。
        """
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"已删除 {count} 个旧事件")

    cleanup_old_events.short_description = "删除选中的事件"


# ========== Admin 站点配置 ==========


def customize_event_admin_site(admin_site):
    """
    自定义事件 Admin 站点

    Args:
        admin_site: Django Admin 站点实例
    """
    # 添加自定义仪表板
    admin_site.site_header = "AgomTradePro 事件管理"
    admin_site.site_title = "事件管理"
    admin_site.index_title = "欢迎使用 AgomTradePro 事件管理系统"
