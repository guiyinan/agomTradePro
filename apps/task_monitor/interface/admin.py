"""
Task Monitor Admin Configuration

Django Admin 配置。
"""

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import SafeString

from apps.task_monitor.models import TaskAlertModel, TaskExecutionModel
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(TaskExecutionModel)
class TaskExecutionAdmin(TypedModelAdmin[TaskExecutionModel]):
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
    readonly_fields = [field.name for field in TaskExecutionModel._meta.fields]
    date_hierarchy = "created_at"

    fieldsets = (
        ("基本信息", {"fields": ("task_id", "task_name", "status", "priority")}),
        ("时间信息", {"fields": ("started_at", "finished_at", "runtime_seconds")}),
        ("执行参数", {"fields": ("args", "kwargs")}),
        ("执行结果", {"fields": ("result", "exception", "traceback")}),
        ("配置信息", {"fields": ("queue", "worker", "retries")}),
        ("元数据", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="状态", ordering="status")
    def status_colored(self, obj: TaskExecutionModel) -> SafeString:
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

    @admin.display(description="优先级", ordering="priority")
    def priority_colored(self, obj: TaskExecutionModel) -> SafeString:
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

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating task execution evidence."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: TaskExecutionModel | None = None,
    ) -> bool:
        """Keep task state, result, exception, and timing evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: TaskExecutionModel | None = None,
    ) -> bool:
        """Require bounded repository retention instead of ad-hoc Admin deletion."""

        del request, obj
        return False


@admin.register(TaskAlertModel)
class TaskAlertAdmin(TypedModelAdmin[TaskAlertModel]):
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
    readonly_fields = [field.name for field in TaskAlertModel._meta.fields]
    date_hierarchy = "triggered_at"

    fieldsets = (
        ("告警信息", {"fields": ("level", "title", "message")}),
        ("任务信息", {"fields": ("task_id", "task_name")}),
        ("异常信息", {"fields": ("exception", "traceback")}),
        ("发送状态", {"fields": ("is_sent", "sent_at", "send_error")}),
        ("元数据", {"fields": ("metadata",)}),
        ("时间信息", {"fields": ("triggered_at",)}),
    )

    @admin.display(description="级别", ordering="level")
    def level_colored(self, obj: TaskAlertModel) -> SafeString:
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

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating task alerts."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: TaskAlertModel | None = None,
    ) -> bool:
        """Keep alert delivery and exception evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: TaskAlertModel | None = None,
    ) -> bool:
        """Prevent ad-hoc deletion of task alert evidence through Admin."""

        del request, obj
        return False
