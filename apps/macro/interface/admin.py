"""
Django Admin configuration for Macro Data.
"""

from django.contrib import admin
from django.utils.html import format_html

from apps.macro.infrastructure.models import (
    IndicatorUnitConfig,
    MacroIndicator,
)



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



@admin.register(IndicatorUnitConfig)
class IndicatorUnitConfigAdmin(admin.ModelAdmin):
    """指标单位配置管理"""

    list_display = [
        'indicator_code', 'source', 'original_unit',
        'is_currency_display', 'priority', 'is_active'
    ]
    list_filter = ['source', 'is_currency', 'is_active']
    search_fields = ['indicator_code', 'original_unit', 'description']
    list_editable = ['is_active']
    ordering = ['-priority', 'indicator_code']

    fieldsets = (
        ('基本信息', {
            'fields': ('indicator_code', 'source', 'original_unit')
        }),
        ('设置', {
            'fields': ('is_currency', 'priority', 'is_active')
        }),
        ('说明', {
            'fields': ('description',)
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def is_currency_display(self, obj):
        """显示是否为货币类指标"""
        status = '是' if obj.is_currency else '否'
        color = 'green' if obj.is_currency else 'gray'
        return format_html('<span style="color:{}">{}</span>', color, status)
    is_currency_display.short_description = '货币类'
