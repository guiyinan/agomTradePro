"""
Terminal Admin Configuration.

Django Admin配置。
"""

from django.contrib import admin

from apps.terminal.application.interface_services import can_create_terminal_runtime_settings
from apps.terminal.models import (
    TerminalAuditLogORM,
    TerminalCommandORM,
    TerminalRuntimeSettingsORM,
)


@admin.register(TerminalCommandORM)
class TerminalCommandAdmin(admin.ModelAdmin):
    """终端命令Admin"""

    list_display = [
        "name",
        "command_type",
        "category",
        "risk_level",
        "requires_mcp",
        "enabled_in_terminal",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "command_type",
        "category",
        "risk_level",
        "requires_mcp",
        "enabled_in_terminal",
        "is_active",
    ]
    search_fields = ["name", "description"]
    ordering = ["category", "name"]

    fieldsets = (
        (
            "基本信息",
            {"fields": ("name", "description", "command_type", "category", "tags", "is_active")},
        ),
        ("治理配置", {"fields": ("risk_level", "requires_mcp", "enabled_in_terminal")}),
        (
            "Prompt配置",
            {
                "classes": ("collapse",),
                "fields": ("prompt_template", "system_prompt", "user_prompt_template"),
            },
        ),
        (
            "API配置",
            {
                "classes": ("collapse",),
                "fields": ("api_endpoint", "api_method", "response_jq_filter"),
            },
        ),
        ("参数定义", {"fields": ("parameters",)}),
        ("执行配置", {"fields": ("timeout", "provider_name", "model_name")}),
    )

    readonly_fields = ["created_at", "updated_at"]


@admin.register(TerminalAuditLogORM)
class TerminalAuditLogAdmin(admin.ModelAdmin):
    """终端审计日志Admin"""

    list_display = [
        "username",
        "command_name",
        "risk_level",
        "mode",
        "result_status",
        "confirmation_status",
        "duration_ms",
        "created_at",
    ]
    list_filter = ["result_status", "confirmation_status", "risk_level", "mode"]
    search_fields = ["username", "command_name"]
    ordering = ["-created_at"]
    readonly_fields = [
        "user",
        "username",
        "session_id",
        "command_name",
        "risk_level",
        "mode",
        "params_summary",
        "confirmation_required",
        "confirmation_status",
        "result_status",
        "error_message",
        "duration_ms",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TerminalRuntimeSettingsORM)
class TerminalRuntimeSettingsAdmin(admin.ModelAdmin):
    """Terminal runtime settings admin."""

    list_display = ["singleton_key", "answer_chain_enabled", "updated_at"]
    readonly_fields = ["singleton_key", "created_at", "updated_at"]
    fieldsets = (
        ("显示开关", {"fields": ("singleton_key", "answer_chain_enabled")}),
        (
            "聊天范围",
            {
                "fields": ("fallback_chat_system_prompt",),
                "description": "控制 Terminal 与共享网页聊天在 fallback 普通对话时的系统提示词范围。",
            },
        ),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return can_create_terminal_runtime_settings()

    def has_delete_permission(self, request, obj=None):
        return False
