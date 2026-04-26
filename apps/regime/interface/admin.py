"""
Django Admin for Regime Interface.

注意：主要的 Admin 配置在 infrastructure/admin.py
此文件保留用于 Interface 层的模型管理。
"""

from django.contrib import admin

from apps.regime.models import RegimeLog


@admin.register(RegimeLog)
class RegimeLogAdmin(admin.ModelAdmin):
    """Admin interface for RegimeLog"""

    list_display = [
        "observed_at",
        "dominant_regime",
        "confidence",
        "growth_momentum_z",
        "inflation_momentum_z",
    ]
    list_filter = ["dominant_regime", "observed_at"]
    date_hierarchy = "observed_at"
    readonly_fields = ["created_at"]
