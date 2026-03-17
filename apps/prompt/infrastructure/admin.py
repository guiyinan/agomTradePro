"""
Admin configuration for Prompt management.
"""

from django.contrib import admin

from .models import (
    PromptTemplateORM,
    ChainConfigORM,
    PromptExecutionLogORM,
    ChatSessionORM,
)


@admin.register(PromptTemplateORM)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'version', 'is_active', 'temperature', 'last_used_at', 'created_at']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'last_used_at']
    ordering = ['category', 'name']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'category', 'version', 'description', 'is_active')
        }),
        ('模板内容', {
            'fields': ('template_content', 'system_prompt', 'placeholders')
        }),
        ('AI参数', {
            'fields': ('temperature', 'max_tokens')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at', 'last_used_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ChainConfigORM)
class ChainConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'execution_mode', 'is_active', 'created_at']
    list_filter = ['category', 'execution_mode', 'is_active']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PromptExecutionLogORM)
class PromptExecutionLogAdmin(admin.ModelAdmin):
    list_display = ['execution_id', 'template', 'status', 'response_time_ms', 'total_tokens', 'created_at']
    list_filter = ['status', 'provider_used']
    search_fields = ['execution_id', 'template__name']
    readonly_fields = [f.name for f in PromptExecutionLogORM._meta.fields]
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ChatSessionORM)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'created_at']
    search_fields = ['session_id', 'user_message']
    readonly_fields = [f.name for f in ChatSessionORM._meta.fields]
    date_hierarchy = 'created_at'