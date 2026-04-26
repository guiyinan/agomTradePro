"""
Django Admin for Investment Signals.
"""

from django.contrib import admin

from apps.signal.models import InvestmentSignalModel


@admin.register(InvestmentSignalModel)
class InvestmentSignalAdmin(admin.ModelAdmin):
    """Admin interface for InvestmentSignalModel"""

    list_display = [
        "asset_code",
        "asset_class",
        "direction",
        "status",
        "target_regime",
        "created_at",
    ]
    list_filter = ["status", "direction", "asset_class", "target_regime"]
    search_fields = ["asset_code", "logic_desc"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("基本信息", {"fields": ("asset_code", "asset_class", "direction", "status")}),
        ("逻辑描述", {"fields": ("logic_desc", "invalidation_logic", "invalidation_threshold")}),
        ("配置", {"fields": ("target_regime",)}),
        ("审核", {"fields": ("rejection_reason",), "classes": ("collapse",)}),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
