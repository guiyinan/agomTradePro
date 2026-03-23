"""
Django Admin 配置 - Shared App

包含所有共享模型的 Admin 配置。
"""

from django.contrib import admin

from .infrastructure.models import (
    AssetConfigModel,
    FilterParameterConfigModel,
    FundTypePreferenceConfigModel,
    HedgingInstrumentConfigModel,
    IndicatorConfigModel,
    RegimeEligibilityConfigModel,
    RiskParameterConfigModel,
    SectorPreferenceConfigModel,
    StockScreeningRuleConfigModel,
    TransactionCostConfigModel,
)


@admin.register(StockScreeningRuleConfigModel)
class StockScreeningRuleConfigAdmin(admin.ModelAdmin):
    """个股筛选规则配置管理"""

    list_display = [
        'regime', 'rule_name', 'min_roe', 'max_pe', 'max_pb',
        'max_count', 'is_active', 'priority', 'updated_at'
    ]
    list_filter = ['regime', 'is_active', 'created_at']
    search_fields = ['rule_name', 'regime']
    ordering = ['-priority', '-created_at']

    fieldsets = (
        ('基础信息', {
            'fields': ('regime', 'rule_name', 'is_active', 'priority')
        }),
        ('财务指标阈值', {
            'fields': ('min_roe', 'min_revenue_growth', 'min_profit_growth', 'max_debt_ratio')
        }),
        ('估值指标阈值', {
            'fields': ('max_pe', 'max_pb', 'min_market_cap')
        }),
        ('行业偏好', {
            'fields': ('sector_preference', 'max_count')
        }),
    )


@admin.register(SectorPreferenceConfigModel)
class SectorPreferenceConfigAdmin(admin.ModelAdmin):
    """板块偏好配置管理"""

    list_display = ['regime', 'sector_name', 'weight', 'is_active', 'updated_at']
    list_filter = ['regime', 'is_active']
    search_fields = ['sector_name']
    ordering = ['regime', '-weight']


@admin.register(FundTypePreferenceConfigModel)
class FundTypePreferenceConfigAdmin(admin.ModelAdmin):
    """基金类型偏好配置管理"""

    list_display = ['regime', 'fund_type', 'style', 'is_active', 'priority', 'updated_at']
    list_filter = ['regime', 'is_active']
    search_fields = ['fund_type', 'style']
    ordering = ['regime', '-priority']


@admin.register(AssetConfigModel)
class AssetConfigModelAdmin(admin.ModelAdmin):
    """资产配置管理"""

    list_display = ['asset_class', 'display_name', 'ticker_symbol', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['asset_class', 'display_name']


@admin.register(IndicatorConfigModel)
class IndicatorConfigModelAdmin(admin.ModelAdmin):
    """指标配置管理"""

    list_display = ['code', 'name', 'category', 'unit', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['code', 'name']


@admin.register(RegimeEligibilityConfigModel)
class RegimeEligibilityConfigModelAdmin(admin.ModelAdmin):
    """Regime 准入配置管理"""

    list_display = ['asset_class', 'regime', 'eligibility', 'weight', 'is_active']
    list_filter = ['regime', 'eligibility', 'is_active']
    search_fields = ['asset_class']


@admin.register(RiskParameterConfigModel)
class RiskParameterConfigModelAdmin(admin.ModelAdmin):
    """风险参数配置管理"""

    list_display = ['key', 'name', 'parameter_type', 'is_active']
    list_filter = ['parameter_type', 'is_active']
    search_fields = ['key', 'name']


@admin.register(FilterParameterConfigModel)
class FilterParameterConfigModelAdmin(admin.ModelAdmin):
    """滤波参数配置管理"""

    list_display = ['key', 'name', 'filter_type', 'is_active']
    list_filter = ['filter_type', 'is_active']
    search_fields = ['key', 'name']


@admin.register(TransactionCostConfigModel)
class TransactionCostConfigModelAdmin(admin.ModelAdmin):
    """交易成本配置管理"""

    list_display = ['market', 'asset_class', 'commission_rate', 'is_active']
    list_filter = ['market', 'asset_class', 'is_active']


@admin.register(HedgingInstrumentConfigModel)
class HedgingInstrumentConfigModelAdmin(admin.ModelAdmin):
    """对冲工具配置管理"""

    list_display = ['instrument_code', 'instrument_name', 'instrument_type', 'is_active']
    list_filter = ['instrument_type', 'is_active']
    search_fields = ['instrument_code', 'instrument_name']
