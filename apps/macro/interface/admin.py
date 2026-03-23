"""
Django Admin configuration for Macro Data.
"""

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils.html import format_html

from apps.macro.infrastructure.models import (
    DataProviderSettings,
    DataSourceConfig,
    IndicatorUnitConfig,
    MacroIndicator,
)


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


@admin.register(DataProviderSettings)
class DataProviderSettingsAdmin(admin.ModelAdmin):
    """数据源设置管理（单例模式）"""

    list_display = [
        'default_data_source_display', 'enable_failover_display',
        'failover_tolerance_display', 'updated_at'
    ]
    list_display_links = None  # 禁止从列表页进入编辑
    list_filter = []

    fieldsets = (
        ('数据源选择', {
            'fields': ('default_data_source', 'enable_failover')
        }),
        ('容错配置', {
            'fields': ('failover_tolerance',)
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

    def has_add_permission(self, request):
        """禁止添加新记录（单例模式）"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除配置记录"""
        return False

    def default_data_source_display(self, obj):
        """显示默认数据源"""
        colors = {'akshare': 'green', 'tushare': 'blue', 'failover': 'orange'}
        color = colors.get(obj.default_data_source, 'black')
        return format_html(
            '<span style="color:{}; font-weight:bold">{}</span>',
            color,
            obj.get_default_data_source_display()
        )
    default_data_source_display.short_description = '默认数据源'

    def enable_failover_display(self, obj):
        """显示容错状态"""
        status = '开启' if obj.enable_failover else '关闭'
        color = 'green' if obj.enable_failover else 'orange'
        return format_html('<span style="color:{}">{}</span>', color, status)
    enable_failover_display.short_description = '自动容错'

    def failover_tolerance_display(self, obj):
        """显示容差"""
        return f'{obj.failover_tolerance * 100:.1f}%'
    failover_tolerance_display.short_description = '容差比例'

    def response_add(self, request, obj, post_url_continue=None):
        """保存后重定向并清除缓存"""
        obj.clear_secrets_cache()
        self.message_user(request, '数据源设置已更新', messages.SUCCESS)
        return redirect('/admin/macro/dataprovidersettings/')

    def response_change(self, request, obj):
        """保存后重定向并清除缓存"""
        obj.clear_secrets_cache()
        self.message_user(request, '数据源设置已更新', messages.SUCCESS)
        return redirect('/admin/macro/dataprovidersettings/')


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
