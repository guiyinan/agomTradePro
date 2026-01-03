"""
Django Admin configuration for Equity Module.
"""

from django.contrib import admin
from apps.equity.infrastructure.models import (
    StockInfoModel,
    StockDailyModel,
    FinancialDataModel,
    ValuationModel,
)


@admin.register(StockInfoModel)
class StockInfoAdmin(admin.ModelAdmin):
    """Admin interface for StockInfo"""

    list_display = [
        'stock_code', 'name', 'sector', 'market',
        'list_date', 'is_active', 'created_at'
    ]
    list_filter = ['market', 'sector', 'is_active']
    search_fields = ['stock_code', 'name', 'sector']
    date_hierarchy = 'list_date'
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('stock_code', 'name', 'sector', 'market', 'list_date')
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(StockDailyModel)
class StockDailyAdmin(admin.ModelAdmin):
    """Admin interface for StockDaily"""

    list_display = [
        'stock_code', 'trade_date', 'close', 'volume',
        'amount', 'turnover_rate', 'change_pct_calculated'
    ]
    list_filter = ['trade_date']
    search_fields = ['stock_code']
    date_hierarchy = 'trade_date'
    readonly_fields = ['created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('stock_code', 'trade_date')
        }),
        ('价格数据', {
            'fields': ('open', 'high', 'low', 'close')
        }),
        ('成交数据', {
            'fields': ('volume', 'amount', 'turnover_rate')
        }),
        ('技术指标', {
            'fields': (
                'ma5', 'ma20', 'ma60',
                'macd', 'macd_signal', 'macd_hist',
                'rsi'
            ),
            'classes': ('collapse',)
        }),
        ('时间戳', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def change_pct_calculated(self, obj):
        """计算涨跌幅"""
        if obj.open and obj.close:
            return round((obj.close - obj.open) / obj.open * 100, 2)
        return '-'
    change_pct_calculated.short_description = '涨跌幅(%)'


@admin.register(FinancialDataModel)
class FinancialDataAdmin(admin.ModelAdmin):
    """Admin interface for FinancialData"""

    list_display = [
        'stock_code', 'report_date', 'report_type',
        'revenue', 'net_profit', 'roe', 'debt_ratio',
        'revenue_growth', 'net_profit_growth'
    ]
    list_filter = ['report_type', 'report_date']
    search_fields = ['stock_code']
    date_hierarchy = 'report_date'
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('stock_code', 'report_date', 'report_type')
        }),
        ('利润表', {
            'fields': ('revenue', 'net_profit', 'revenue_growth', 'net_profit_growth')
        }),
        ('资产负债表', {
            'fields': ('total_assets', 'total_liabilities', 'equity')
        }),
        ('财务指标', {
            'fields': ('roe', 'roa', 'debt_ratio')
        }),
        ('元数据', {
            'fields': ('publish_date', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ValuationModel)
class ValuationAdmin(admin.ModelAdmin):
    """Admin interface for Valuation"""

    list_display = [
        'stock_code', 'trade_date', 'pe_ttm', 'pb',
        'total_mv_display', 'circ_mv_display', 'dividend_yield'
    ]
    list_filter = ['trade_date']
    search_fields = ['stock_code']
    date_hierarchy = 'trade_date'
    readonly_fields = ['created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('stock_code', 'trade_date')
        }),
        ('估值指标', {
            'fields': ('pe', 'pe_ttm', 'pb', 'ps', 'dividend_yield')
        }),
        ('市值', {
            'fields': ('total_mv', 'circ_mv')
        }),
        ('时间戳', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def total_mv_display(self, obj):
        """格式化总市值显示"""
        if obj.total_mv:
            if obj.total_mv >= 100000000000:
                return f"{obj.total_mv / 100000000:.1f}亿"
            return f"{obj.total_mv / 10000:.0f}万"
        return '-'
    total_mv_display.short_description = '总市值'

    def circ_mv_display(self, obj):
        """格式化流通市值显示"""
        if obj.circ_mv:
            if obj.circ_mv >= 100000000000:
                return f"{obj.circ_mv / 100000000:.1f}亿"
            return f"{obj.circ_mv / 10000:.0f}万"
        return '-'
    circ_mv_display.short_description = '流通市值'
