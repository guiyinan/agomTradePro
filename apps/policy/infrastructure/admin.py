"""
Django Admin 配置 - Policy 模块
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    PolicyLog,
    RSSSourceConfigModel,
    PolicyLevelKeywordModel,
    RSSFetchLog,
    PolicyAuditQueue,
    HedgePositionModel,
)


@admin.register(PolicyLog)
class PolicyLogAdmin(admin.ModelAdmin):
    """政策事件日志管理"""

    list_display = ['event_date', 'level', 'title', 'info_category', 'audit_status', 'risk_impact', 'created_at']
    list_filter = ['level', 'info_category', 'audit_status', 'risk_impact', 'event_date']
    search_fields = ['title', 'description', 'evidence_url']
    list_editable = ['audit_status', 'risk_impact']
    ordering = ['-event_date']
    date_hierarchy = 'event_date'

    fieldsets = (
        ('基本信息', {
            'fields': ('event_date', 'level', 'title', 'description')
        }),
        ('来源', {
            'fields': ('evidence_url', 'rss_source', 'rss_item_guid')
        }),
        ('分类', {
            'fields': ('info_category', 'risk_impact')
        }),
        ('审核', {
            'fields': ('audit_status', 'ai_confidence', 'reviewed_by', 'reviewed_at', 'review_notes')
        }),
        ('结构化数据', {
            'fields': ('structured_data', 'processing_metadata'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at']


@admin.register(RSSSourceConfigModel)
class RSSSourceConfigAdmin(admin.ModelAdmin):
    """RSS源配置管理"""

    list_display = ['name', 'category', 'url', 'is_active', 'fetch_interval_hours', 'last_fetch_at', 'last_fetch_status']
    list_filter = ['category', 'is_active', 'parser_type']
    search_fields = ['name', 'url']
    list_editable = ['is_active', 'fetch_interval_hours']
    ordering = ['category', 'name']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'url', 'category')
        }),
        ('抓取配置', {
            'fields': ('is_active', 'fetch_interval_hours', 'extract_content')
        }),
        ('代理设置', {
            'fields': ('proxy_enabled', 'proxy_host', 'proxy_port', 'proxy_type'),
            'classes': ('collapse',)
        }),
        ('解析器配置', {
            'fields': ('parser_type', 'timeout_seconds', 'retry_times')
        }),
        ('状态监控', {
            'fields': ('last_fetch_at', 'last_fetch_status', 'last_error_message'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['last_fetch_at', 'last_fetch_status', 'last_error_message']


@admin.register(PolicyLevelKeywordModel)
class PolicyLevelKeywordAdmin(admin.ModelAdmin):
    """政策档位关键词规则管理"""

    list_display = ['level', 'keywords_preview', 'weight', 'category', 'is_active']
    list_filter = ['level', 'category', 'is_active']
    search_fields = ['keywords']
    list_editable = ['is_active']
    ordering = ['-weight', 'level']

    def keywords_preview(self, obj):
        keywords_str = ', '.join(obj.keywords[:5])
        if len(obj.keywords) > 5:
            keywords_str += f' ... (+{len(obj.keywords) - 5})'
        return keywords_str
    keywords_preview.short_description = '关键词'


@admin.register(RSSFetchLog)
class RSSFetchLogAdmin(admin.ModelAdmin):
    """RSS抓取日志管理"""

    list_display = ['source', 'fetched_at', 'status', 'items_count', 'new_items_count', 'fetch_duration_seconds']
    list_filter = ['status', 'fetched_at']
    search_fields = ['source__name', 'error_message']
    date_hierarchy = 'fetched_at'
    ordering = ['-fetched_at']
    readonly_fields = ['fetched_at']


@admin.register(PolicyAuditQueue)
class PolicyAuditQueueAdmin(admin.ModelAdmin):
    """政策审核队列管理"""

    list_display = ['policy_log_display', 'priority', 'assigned_to', 'assigned_at', 'due_date']
    list_filter = ['priority', 'assigned_to', 'created_at']
    search_fields = ['policy_log__title']
    list_editable = ['priority', 'assigned_to']
    ordering = ['priority', '-created_at']

    def policy_log_display(self, obj):
        return obj.policy_log.title[:50]
    policy_log_display.short_description = '政策事件'


# ============================================================
# Phase 6: 风控体系 - 对冲持仓管理
# ============================================================

@admin.register(HedgePositionModel)
class HedgePositionAdmin(admin.ModelAdmin):
    """对冲持仓记录管理"""

    list_display = ['portfolio', 'instrument_code', 'instrument_type', 'hedge_ratio_display', 'hedge_value', 'policy_level', 'status', 'executed_at']
    list_filter = ['status', 'policy_level', 'instrument_type', 'created_at', 'executed_at']
    search_fields = ['portfolio__name', 'instrument_code']
    list_editable = ['status']
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('portfolio', 'instrument_code', 'instrument_type')
        }),
        ('对冲参数', {
            'fields': ('hedge_ratio', 'hedge_value', 'policy_level')
        }),
        ('执行信息', {
            'fields': ('execution_price', 'executed_at', 'status')
        }),
        ('成本', {
            'fields': ('opening_cost', 'closing_cost', 'total_cost')
        }),
        ('效果评估', {
            'fields': ('beta_before', 'beta_after', 'hedge_profit')
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def hedge_ratio_display(self, obj):
        color = 'green' if obj.hedge_ratio > 0 else 'gray'
        return format_html('<span style="color:{}">{:.1f}%</span>', color, obj.hedge_ratio * 100)
    hedge_ratio_display.short_description = '对冲比例'
