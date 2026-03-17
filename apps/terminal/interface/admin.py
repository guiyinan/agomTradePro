"""
Terminal Admin Configuration.

Django Admin配置。
"""

from django.contrib import admin
from ..infrastructure.models import TerminalCommandORM


@admin.register(TerminalCommandORM)
class TerminalCommandAdmin(admin.ModelAdmin):
    """终端命令Admin"""
    
    list_display = ['name', 'command_type', 'category', 'is_active', 'created_at']
    list_filter = ['command_type', 'category', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['category', 'name']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'command_type', 'category', 'tags', 'is_active')
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
