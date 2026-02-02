"""
Django Admin for Regime Infrastructure - 增强版

提供更易用、更专业的管理界面。
"""

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import (
    RegimeThresholdConfig,
    RegimeIndicatorThreshold,
)


class RegimeIndicatorThresholdInline(admin.TabularInline):
    """指标阈值内联编辑"""
    model = RegimeIndicatorThreshold
    extra = 0
    min_num = 2  # 至少需要 PMI 和 CPI
    fields = ['indicator_code', 'indicator_name', 'level_low', 'level_high', 'description']


@admin.register(RegimeThresholdConfig)
class RegimeThresholdConfigAdmin(admin.ModelAdmin):
    """Regime 阈值配置 - 增强版"""

    list_display = [
        'name',
        'status_badge',
        'indicators_count',
        'threshold_summary',
        'created_at',
        'updated_at',
        'activate_action'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']

    inlines = [RegimeIndicatorThresholdInline]

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'is_active', 'description')
        }),
        ('指标阈值（通过下方表格编辑）', {
            'fields': ()
        }),
        ('系统信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj):
        """状态徽章"""
        if obj.is_active:
            return format_html(
                '<span style="background: #22c55e; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;">激活中</span>'
            )
        else:
            return format_html(
                '<span style="background: #94a3b8; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;">未激活</span>'
            )
    status_badge.short_description = '状态'

    def indicators_count(self, obj):
        """指标数量"""
        count = obj.thresholds.count()
        return f'{count} 个指标'
    indicators_count.short_description = '指标数量'

    def threshold_summary(self, obj):
        """阈值摘要"""
        lines = []
        for t in obj.thresholds.all():
            lines.append(f'{t.indicator_code}: 低={t.level_low}, 高={t.level_high}')
        return mark_safe('<br>'.join(lines) if lines else '未配置')
    threshold_summary.short_description = '阈值摘要'

    def activate_action(self, obj):
        """激活操作按钮"""
        if obj.is_active:
            return '已是激活状态'

        url = reverse('admin:regime_regimethresholdconfig_activate', args=[obj.pk])
        return format_html(
            '<a href="{}" class="button" style="padding: 4px 8px; background: #22c55e; color: white; text-decoration: none; border-radius: 4px;">激活此配置</a>',
            url
        )
    activate_action.short_description = '操作'

    def get_urls(self):
        """添加自定义 URL"""
        from django.urls import path
        from .views import activate_regime_config

        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/activate/',
                self.admin_site.admin_view(activate_regime_config),
                name='regime_regimethresholdconfig_activate'
            )
        ]
        return custom_urls + urls


@admin.register(RegimeIndicatorThreshold)
class RegimeIndicatorThresholdAdmin(admin.ModelAdmin):
    """指标阈值 - 单独管理（可选）"""

    list_display = [
        'indicator_code',
        'indicator_name',
        'config_name',
        'threshold_range',
        'description'
    ]
    list_filter = ['config', 'indicator_code']
    search_fields = ['indicator_code', 'indicator_name', 'description']

    def config_name(self, obj):
        return obj.config.name
    config_name.short_description = '配置名称'

    def threshold_range(self, obj):
        """阈值范围显示"""
        return f'{obj.level_low} ~ {obj.level_high}'
    threshold_range.short_description = '阈值范围'


# 自定义 Admin 站点配置
class RegimeAdminSite(admin.AdminSite):
    """可选：独立的 Regime 管理站点"""
    site_header = 'AgomSAAF Regime 管理'
    site_title = 'Regime 配置'
    index_title = '欢迎使用 Regime 配置系统'

    site_url = '/regime/admin/'


# 创建专用站点实例（可选，如果要使用独立的管理站点）
# regime_admin_site = RegimeAdminSite()
# regime_admin_site.register(RegimeLog, RegimeLogAdmin)
# regime_admin_site.register(RegimeThresholdConfig, RegimeThresholdConfigAdmin)
