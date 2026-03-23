"""
Django Admin 配置 - Shared 模块
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AssetConfigModel,
    FilterParameterConfigModel,
    HedgingInstrumentConfigModel,
    IndicatorConfigModel,
    RegimeEligibilityConfigModel,
    RiskParameterConfigModel,
    TransactionCostConfigModel,
)


@admin.register(AssetConfigModel)
class AssetConfigAdmin(admin.ModelAdmin):
    """资产类别配置管理"""

    list_display = ['asset_class', 'display_name', 'ticker_symbol', 'data_source', 'category', 'is_active']
    list_filter = ['category', 'is_active', 'data_source']
    search_fields = ['asset_class', 'display_name', 'ticker_symbol']
    list_editable = ['is_active']
    ordering = ['category', 'asset_class']


@admin.register(IndicatorConfigModel)
class IndicatorConfigAdmin(admin.ModelAdmin):
    """宏观指标配置管理"""

    list_display = ['code', 'name', 'category', 'unit', 'data_source', 'publication_lag_days', 'is_active']
    list_filter = ['category', 'is_active', 'data_source']
    search_fields = ['code', 'name', 'name_en']
    list_editable = ['is_active']
    ordering = ['category', 'code']


@admin.register(RegimeEligibilityConfigModel)
class RegimeEligibilityConfigAdmin(admin.ModelAdmin):
    """Regime 准入矩阵配置管理"""

    list_display = ['asset_class', 'regime', 'eligibility', 'weight', 'adjustment_factor', 'is_active']
    list_filter = ['regime', 'eligibility', 'is_active']
    search_fields = ['asset_class']
    list_editable = ['eligibility', 'weight', 'adjustment_factor', 'is_active']
    ordering = ['asset_class', 'regime']

    def eligibility_display(self, obj):
        colors = {
            'preferred': 'green',
            'neutral': 'gray',
            'hostile': 'red'
        }
        color = colors.get(obj.eligibility, 'black')
        return format_html('<span style="color:{}">{}</span>', color, obj.get_eligibility_display())
    eligibility_display.short_description = '准入状态'


@admin.register(RiskParameterConfigModel)
class RiskParameterConfigAdmin(admin.ModelAdmin):
    """风险参数配置管理"""

    list_display = ['key', 'name', 'parameter_type', 'value_display', 'policy_level', 'regime', 'is_active']
    list_filter = ['parameter_type', 'policy_level', 'is_active']
    search_fields = ['key', 'name', 'description']
    list_editable = ['is_active']
    ordering = ['parameter_type', 'key']

    def value_display(self, obj):
        if obj.value_float is not None:
            return f'{obj.value_float}'
        elif obj.value_string:
            return obj.value_string[:20]
        elif obj.value_json:
            return f'<JSON: {len(str(obj.value_json))} chars>'
        return '-'
    value_display.short_description = '参数值'


@admin.register(FilterParameterConfigModel)
class FilterParameterConfigAdmin(admin.ModelAdmin):
    """滤波参数配置管理"""

    list_display = ['key', 'name', 'filter_type', 'data_frequency', 'indicator_category', 'is_active']
    list_filter = ['filter_type', 'data_frequency', 'indicator_category', 'is_active']
    search_fields = ['key', 'name', 'description']
    list_editable = ['is_active']
    ordering = ['filter_type', 'key']


# ============================================================
# Phase 6: 风控体系 - 交易成本与对冲工具配置
# ============================================================

@admin.register(TransactionCostConfigModel)
class TransactionCostConfigAdmin(admin.ModelAdmin):
    """交易成本配置管理"""

    list_display = ['market', 'asset_class', 'commission_rate_display', 'stamp_duty_rate_display', 'cost_warning_threshold_display', 'is_active']
    list_filter = ['market', 'asset_class', 'is_active']
    search_fields = ['market', 'asset_class']
    list_editable = ['is_active']
    ordering = ['market', 'asset_class']

    fieldsets = (
        ('基本信息', {
            'fields': ('market', 'asset_class')
        }),
        ('成本费率', {
            'fields': ('commission_rate', 'slippage_rate', 'stamp_duty_rate', 'transfer_fee_rate')
        }),
        ('最小费用', {
            'fields': ('min_commission',)
        }),
        ('预警', {
            'fields': ('cost_warning_threshold',)
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    def commission_rate_display(self, obj):
        return format_html('{:.4%}', obj.commission_rate)
    commission_rate_display.short_description = '佣金费率'

    def stamp_duty_rate_display(self, obj):
        return format_html('{:.4%}', obj.stamp_duty_rate)
    stamp_duty_rate_display.short_description = '印花税率'

    def cost_warning_threshold_display(self, obj):
        color = 'orange' if obj.cost_warning_threshold > 0.005 else 'green'
        return format_html('<span style="color:{}">{:.2%}</span>', color, obj.cost_warning_threshold)
    cost_warning_threshold_display.short_description = '预警阈值'


@admin.register(HedgingInstrumentConfigModel)
class HedgingInstrumentConfigAdmin(admin.ModelAdmin):
    """对冲工具配置管理"""

    list_display = ['instrument_code', 'instrument_name', 'instrument_type', 'hedge_ratio_display', 'cost_bps_display', 'underlying_index', 'is_active']
    list_filter = ['instrument_type', 'is_active']
    search_fields = ['instrument_code', 'instrument_name', 'underlying_index']
    list_editable = ['is_active']
    ordering = ['instrument_type', 'instrument_code']

    fieldsets = (
        ('基本信息', {
            'fields': ('instrument_code', 'instrument_name', 'instrument_type')
        }),
        ('对冲参数', {
            'fields': ('hedge_ratio', 'underlying_index')
        }),
        ('成本', {
            'fields': ('cost_bps',)
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    def hedge_ratio_display(self, obj):
        color = 'green' if obj.hedge_ratio >= 0.9 else 'orange' if obj.hedge_ratio >= 0.5 else 'red'
        return format_html('<span style="color:{}">{:.1f}%</span>', color, obj.hedge_ratio * 100)
    hedge_ratio_display.short_description = '对冲比例'

    def cost_bps_display(self, obj):
        return f'{obj.cost_bps:.1f} bps'
    cost_bps_display.short_description = '对冲成本'
