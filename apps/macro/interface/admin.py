"""
Django Admin configuration for Macro Data.
"""

from django.contrib import admin
from apps.macro.infrastructure.models import MacroIndicator, DataSourceConfig


@admin.register(DataSourceConfig)
class DataSourceConfigAdmin(admin.ModelAdmin):
    """Admin interface for DataSourceConfig"""

    list_display = [
        'name', 'source_type', 'is_active', 'priority',
        'api_endpoint', 'created_at'
    ]
    list_filter = ['source_type', 'is_active', 'priority']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'source_type', 'description')
        }),
        ('配置', {
            'fields': (
                'is_active', 'priority',
                'api_endpoint', 'api_key', 'api_secret', 'extra_config'
            )
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        """保存时隐藏 API 密钥的部分内容"""
        if obj.api_key and len(obj.api_key) > 8:
            # 在日志中不记录完整密钥
            pass
        super().save_model(request, obj, form, change)


@admin.register(MacroIndicator)
class MacroIndicatorAdmin(admin.ModelAdmin):
    """Admin interface for MacroIndicator"""

    list_display = [
        'code', 'value', 'reporting_period', 'period_type',
        'published_at', 'source', 'revision_number', 'created_at'
    ]
    list_filter = ['code', 'source', 'period_type', 'reporting_period']
    search_fields = ['code']
    date_hierarchy = 'reporting_period'
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('数据', {
            'fields': ('code', 'value', 'reporting_period', 'period_type')
        }),
        ('元数据', {
            'fields': (
                'published_at', 'publication_lag_days',
                'source', 'revision_number'
            )
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
