"""
Task Monitor Admin Configuration

Django Admin 配置。
"""

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from apps.task_monitor.models import TaskAlertModel, TaskExecutionModel


@admin.register(TaskExecutionModel)
class TaskExecutionAdmin(admin.ModelAdmin):
    """任务执行记录 Admin"""

    list_display = [
        "task_name",
        "task_id",
        "status_colored",
        "started_at",
        "finished_at",
        "runtime_seconds",
        "retries",
        "priority_colored",
        "worker",
    ]
    list_filter = ["status", "priority", "queue", "created_at"]
    search_fields = ["task_id", "task_name", "exception"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        ("基本信息", {"fields": ("task_id", "task_name", "status", "priority")}),
        ("时间信息", {"fields": ("started_at", "finished_at", "runtime_seconds")}),
        ("执行参数", {"fields": ("args", "kwargs")}),
        ("执行结果", {"fields": ("result", "exception", "traceback")}),
        ("配置信息", {"fields": ("queue", "worker", "retries")}),
        ("元数据", {"fields": ("created_at", "updated_at")}),
    )

    def status_colored(self, obj: TaskExecutionModel) -> str:
        """带颜色的状态显示"""
        colors = {
            "pending": "gray",
            "started": "blue",
            "success": "green",
            "failure": "red",
            "retry": "orange",
            "revoked": "purple",
            "timeout": "darkred",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_colored.short_description = "状态"
    status_colored.admin_order_field = "status"

    def priority_colored(self, obj: TaskExecutionModel) -> str:
        """带颜色的优先级显示"""
        colors = {
            "low": "gray",
            "normal": "blue",
            "high": "orange",
            "critical": "red",
        }
        color = colors.get(obj.priority, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_priority_display(),
        )

    priority_colored.short_description = "优先级"
    priority_colored.admin_order_field = "priority"

    def get_queryset(self, request):
        """优化查询性能"""
        qs = super().get_queryset(request)
        return qs.select_related().annotate(_status_count=Count("id"))


@admin.register(TaskAlertModel)
class TaskAlertAdmin(admin.ModelAdmin):
    """任务告警记录 Admin"""

    list_display = [
        "level_colored",
        "task_name",
        "title",
        "is_sent",
        "triggered_at",
    ]
    list_filter = ["level", "is_sent", "triggered_at"]
    search_fields = ["task_id", "task_name", "title", "message"]
    readonly_fields = ["triggered_at", "sent_at"]
    date_hierarchy = "triggered_at"

    fieldsets = (
        ("告警信息", {"fields": ("level", "title", "message")}),
        ("任务信息", {"fields": ("task_id", "task_name")}),
        ("异常信息", {"fields": ("exception", "traceback")}),
        ("发送状态", {"fields": ("is_sent", "sent_at", "send_error")}),
        ("元数据", {"fields": ("metadata",)}),
        ("时间信息", {"fields": ("triggered_at",)}),
    )

    def level_colored(self, obj: TaskAlertModel) -> str:
        """带颜色的级别显示"""
        colors = {
            "info": "blue",
            "warning": "orange",
            "critical": "red",
        }
        color = colors.get(obj.level, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_level_display(),
        )

    level_colored.short_description = "级别"
    level_colored.admin_order_field = "level"
