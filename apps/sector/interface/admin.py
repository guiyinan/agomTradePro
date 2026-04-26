"""
Django Admin configuration for Sector Module.
"""

from django.contrib import admin

from apps.sector.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
    SectorRelativeStrengthModel,
)


@admin.register(SectorInfoModel)
class SectorInfoAdmin(admin.ModelAdmin):
    """Admin interface for SectorInfo"""

    list_display = ["sector_code", "sector_name", "level", "parent_code", "is_active", "created_at"]
    list_filter = ["level", "is_active"]
    search_fields = ["sector_code", "sector_name"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("基本信息", {"fields": ("sector_code", "sector_name", "level")}),
        ("层级关系", {"fields": ("parent_code",)}),
        ("状态", {"fields": ("is_active",)}),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(SectorIndexModel)
class SectorIndexAdmin(admin.ModelAdmin):
    """Admin interface for SectorIndex"""

    list_display = [
        "sector_code",
        "trade_date",
        "close",
        "change_pct",
        "volume",
        "amount",
        "turnover_rate",
    ]
    list_filter = ["trade_date"]
    search_fields = ["sector_code"]
    date_hierarchy = "trade_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("sector_code", "trade_date")}),
        ("价格数据", {"fields": ("open_price", "high", "low", "close", "change_pct")}),
        ("成交数据", {"fields": ("volume", "amount", "turnover_rate")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(SectorConstituentModel)
class SectorConstituentAdmin(admin.ModelAdmin):
    """Admin interface for SectorConstituent"""

    list_display = ["sector_code", "stock_code", "enter_date", "exit_date", "is_current"]
    list_filter = ["is_current", "enter_date"]
    search_fields = ["sector_code", "stock_code"]
    date_hierarchy = "enter_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("关系信息", {"fields": ("sector_code", "stock_code")}),
        ("时间信息", {"fields": ("enter_date", "exit_date")}),
        ("状态", {"fields": ("is_current",)}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(SectorRelativeStrengthModel)
class SectorRelativeStrengthAdmin(admin.ModelAdmin):
    """Admin interface for SectorRelativeStrength"""

    list_display = [
        "sector_code",
        "trade_date",
        "relative_strength",
        "momentum",
        "momentum_window",
        "beta",
    ]
    list_filter = ["trade_date", "momentum_window"]
    search_fields = ["sector_code"]
    date_hierarchy = "trade_date"
    readonly_fields = ["created_at"]

    fieldsets = (
        ("基本信息", {"fields": ("sector_code", "trade_date")}),
        ("相对强弱指标", {"fields": ("relative_strength", "momentum", "momentum_window", "beta")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
