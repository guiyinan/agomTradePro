"""
Django Admin configuration for Equity Module.
"""

from django.contrib import admin

from apps.equity.infrastructure.models import (
    FinancialDataModel,
    ScoringWeightConfigModel,
    StockDailyModel,
    StockInfoModel,
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


@admin.register(ScoringWeightConfigModel)
class ScoringWeightConfigAdmin(admin.ModelAdmin):
    """Admin interface for ScoringWeightConfig"""

    list_display = [
        'name', 'is_active', 'total_weight_check',
        'growth_weight', 'profitability_weight', 'valuation_weight',
        'created_at', 'updated_at'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('评分维度权重（总和必须为 1.0）', {
            'fields': (
                'growth_weight',
                'profitability_weight',
                'valuation_weight'
            )
        }),
        ('成长性内部权重（总和必须为 1.0）', {
            'fields': (
                'revenue_growth_weight',
                'profit_growth_weight'
            )
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def total_weight_check(self, obj):
        """显示权重总和检查"""
        dimension_total = obj.growth_weight + obj.profitability_weight + obj.valuation_weight
        growth_total = obj.revenue_growth_weight + obj.profit_growth_weight

        dimension_status = "✓" if abs(dimension_total - 1.0) < 0.01 else f"✗ ({dimension_total:.2f})"
        growth_status = "✓" if abs(growth_total - 1.0) < 0.01 else f"✗ ({growth_total:.2f})"

        return f"维度: {dimension_status} | 成长性: {growth_status}"
    total_weight_check.short_description = '权重检查'

    def save_model(self, request, obj, form, change):
        """保存前确保只有一个启用的配置"""
        if obj.is_active:
            # 将其他配置设为不启用
            ScoringWeightConfigModel._default_manager.filter(
                is_active=True
            ).exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        """添加后提示用户如果需要启用该配置"""
        if not obj.is_active:
            from django.contrib import messages
            messages.info(
                request,
                '配置已保存。如需启用此配置，请在编辑页面勾选"是否启用" '
                '（这会将其他配置设为不启用状态）。'
            )
        return super().response_add(request, obj, post_url_continue)

