"""
Terminal Admin Configuration.

Django Admin配置。
"""

from django.contrib import admin
from ..infrastructure.models import TerminalAuditLogORM, TerminalCommandORM


@admin.register(TerminalCommandORM)
class TerminalCommandAdmin(admin.ModelAdmin):
    """终端命令Admin"""

    list_display = [
        'name', 'command_type', 'category', 'risk_level',
        'requires_mcp', 'enabled_in_terminal', 'is_active', 'created_at',
    ]
    list_filter = ['command_type', 'category', 'risk_level', 'requires_mcp', 'enabled_in_terminal', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['category', 'name']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'command_type', 'category', 'tags', 'is_active')
        }),
        ('治理配置', {
            'fields': ('risk_level', 'requires_mcp', 'enabled_in_terminal')
        }),
        ('Prompt配置', {
            'classes': ('collapse',),
            'fields': ('prompt_template', 'system_prompt', 'user_prompt_template')
        }),
        ('API配置', {
            'classes': ('collapse',),
            'fields': ('api_endpoint', 'api_method', 'response_jq_filter')
        }),
        ('参数定义', {
            'fields': ('parameters',)
        }),
        ('执行配置', {
            'fields': ('timeout', 'provider_name', 'model_name')
        }),
    )

    readonly_fields = ['created_at', 'updated_at']


@admin.register(TerminalAuditLogORM)
class TerminalAuditLogAdmin(admin.ModelAdmin):
    """终端审计日志Admin"""

    list_display = [
        'username', 'command_name', 'risk_level', 'mode',
        'result_status', 'confirmation_status', 'duration_ms', 'created_at',
    ]
    list_filter = ['result_status', 'confirmation_status', 'risk_level', 'mode']
    search_fields = ['username', 'command_name']
    ordering = ['-created_at']
    readonly_fields = [
        'user', 'username', 'session_id', 'command_name', 'risk_level',
        'mode', 'params_summary', 'confirmation_required', 'confirmation_status',
        'result_status', 'error_message', 'duration_ms', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
