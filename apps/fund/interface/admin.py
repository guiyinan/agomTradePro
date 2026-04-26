"""
Django Admin configuration for Fund Module.
"""

from django.contrib import admin

from apps.fund.models import (
    FundHoldingModel,
    FundInfoModel,
    FundManagerModel,
    FundNetValueModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
)


@admin.register(FundInfoModel)
class FundInfoAdmin(admin.ModelAdmin):
    """Admin interface for FundInfo"""

    list_display = [
        "fund_code",
        "fund_name",
        "fund_type",
        "investment_style",
        "management_company",
        "setup_date",
        "fund_scale_display",
        "is_active",
    ]
    list_filter = ["fund_type", "investment_style", "is_active"]
    search_fields = ["fund_code", "fund_name", "management_company"]
    date_hierarchy = "setup_date"
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "fund_name", "fund_type", "investment_style")}),
        ("机构信息", {"fields": ("management_company", "custodian")}),
        ("规模信息", {"fields": ("setup_date", "fund_scale")}),
        ("状态", {"fields": ("is_active",)}),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def fund_scale_display(self, obj):
        """格式化基金规模显示"""
        if obj.fund_scale:
            if obj.fund_scale >= 100000000:
                return f"{obj.fund_scale / 100000000:.2f}亿"
            return f"{obj.fund_scale / 10000:.0f}万"
        return "-"

    fund_scale_display.short_description = "基金规模"


@admin.register(FundManagerModel)
class FundManagerAdmin(admin.ModelAdmin):
    """Admin interface for FundManager"""

    list_display = [
        "fund_code",
        "manager_name",
        "tenure_start",
        "tenure_end",
        "total_tenure_days",
        "fund_return",
        "is_current",
    ]
    list_filter = ["is_current", "tenure_start"]
    search_fields = ["fund_code", "manager_name"]
    date_hierarchy = "tenure_start"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "manager_name")}),
        ("任期信息", {"fields": ("tenure_start", "tenure_end", "total_tenure_days")}),
        ("业绩表现", {"fields": ("fund_return",)}),
        ("状态", {"fields": ("is_current",)}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(FundNetValueModel)
class FundNetValueAdmin(admin.ModelAdmin):
    """Admin interface for FundNetValue"""

    list_display = ["fund_code", "nav_date", "unit_nav", "accum_nav", "daily_return"]
    list_filter = ["nav_date"]
    search_fields = ["fund_code"]
    date_hierarchy = "nav_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "nav_date")}),
        ("净值数据", {"fields": ("unit_nav", "accum_nav", "daily_return")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(FundHoldingModel)
class FundHoldingAdmin(admin.ModelAdmin):
    """Admin interface for FundHolding"""

    list_display = [
        "fund_code",
        "report_date",
        "stock_code",
        "stock_name",
        "holding_ratio",
        "holding_value_display",
    ]
    list_filter = ["report_date"]
    search_fields = ["fund_code", "stock_code", "stock_name"]
    date_hierarchy = "report_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "report_date")}),
        (
            "持仓信息",
            {
                "fields": (
                    "stock_code",
                    "stock_name",
                    "holding_amount",
                    "holding_value",
                    "holding_ratio",
                )
            },
        ),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def holding_value_display(self, obj):
        """格式化持仓市值显示"""
        if obj.holding_value:
            if obj.holding_value >= 100000000:
                return f"{obj.holding_value / 100000000:.2f}亿"
            return f"{obj.holding_value / 10000:.0f}万"
        return "-"

    holding_value_display.short_description = "持仓市值"


@admin.register(FundSectorAllocationModel)
class FundSectorAllocationAdmin(admin.ModelAdmin):
    """Admin interface for FundSectorAllocation"""

    list_display = ["fund_code", "report_date", "sector_name", "allocation_ratio"]
    list_filter = ["report_date"]
    search_fields = ["fund_code", "sector_name"]
    date_hierarchy = "report_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "report_date")}),
        ("配置信息", {"fields": ("sector_name", "allocation_ratio")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(FundPerformanceModel)
class FundPerformanceAdmin(admin.ModelAdmin):
    """Admin interface for FundPerformance"""

    list_display = [
        "fund_code",
        "start_date",
        "end_date",
        "total_return",
        "annualized_return",
        "volatility",
        "max_drawdown",
        "sharpe_ratio",
        "alpha",
        "beta",
    ]
    list_filter = ["end_date"]
    search_fields = ["fund_code"]
    date_hierarchy = "end_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("fund_code", "start_date", "end_date")}),
        ("收益指标", {"fields": ("total_return", "annualized_return")}),
        ("风险指标", {"fields": ("volatility", "max_drawdown")}),
        ("风险调整收益", {"fields": ("sharpe_ratio", "alpha", "beta")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
