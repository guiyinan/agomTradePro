"""
Django Admin Configuration for AI Provider Management.

管理后台配置。
"""

from django.contrib import admin
from django.db.models import Sum, Count
from datetime import date

from ..infrastructure.models import AIProviderConfig, AIUsageLog


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(admin.ModelAdmin):
    """AI提供商配置管理"""

    list_display = [
        'name',
        'provider_type',
        'is_active',
        'priority',
        'default_model',
        'api_mode',
        'fallback_enabled',
        'last_used_at',
        'created_at'
    ]
    list_filter = ['provider_type', 'is_active']
    search_fields = ['name', 'description', 'base_url']
    ordering = ['priority', 'name']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'provider_type', 'description')
        }),
        ('连接配置', {
            'fields': ('base_url', 'api_key', 'default_model', 'api_mode', 'fallback_enabled')
        }),
        ('状态与优先级', {
            'fields': ('is_active', 'priority')
        }),
        ('预算控制', {
            'fields': ('daily_budget_limit', 'monthly_budget_limit')
        }),
        ('额外配置', {
            'fields': ('extra_config',),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at', 'last_used_at']


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    """AI调用日志管理"""

    list_display = [
        'id',
        'provider',
        'model',
        'status',
        'total_tokens',
        'estimated_cost',
        'response_time_ms',
        'created_at'
    ]
    list_filter = ['status', 'provider', 'model', 'request_type']
    search_fields = ['error_message']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    readonly_fields = [
        'provider',
        'model',
        'request_type',
        'prompt_tokens',
        'completion_tokens',
        'total_tokens',
        'estimated_cost',
        'response_time_ms',
        'status',
        'error_message',
        'request_metadata',
        'created_at'
    ]

    # 每页显示更多记录
    list_per_page = 50

    def has_add_permission(self, request):
        # 不允许手动添加日志
        return False

    def has_change_permission(self, request, obj=None):
        # 日志记录不允许修改
        return False
