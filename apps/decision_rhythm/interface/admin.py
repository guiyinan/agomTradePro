"""
Decision Rhythm Django Admin Configuration

决策频率约束和配额管理的 Django Admin 配置。
"""

from django.contrib import admin

from apps.decision_rhythm.models import (
    CooldownPeriodModel,
    DecisionQuotaModel,
    DecisionRequestModel,
)


@admin.register(DecisionQuotaModel)
class DecisionQuotaAdmin(admin.ModelAdmin):
    """决策配额 Admin"""

    list_display = [
        "quota_id",
        "period",
        "max_decisions",
        "used_decisions",
        "period_start",
        "period_end",
        "created_at",
    ]

    list_filter = [
        "period",
        "created_at",
    ]

    search_fields = [
        "quota_id",
    ]


@admin.register(CooldownPeriodModel)
class CooldownPeriodAdmin(admin.ModelAdmin):
    """冷却期 Admin"""

    list_display = [
        "cooldown_id",
        "asset_code",
        "min_decision_interval_hours",
        "min_execution_interval_hours",
        "same_asset_cooldown_hours",
        "last_decision_at",
        "created_at",
    ]

    list_filter = [
        "created_at",
    ]

    search_fields = [
        "cooldown_id",
        "asset_code",
    ]


@admin.register(DecisionRequestModel)
class DecisionRequestAdmin(admin.ModelAdmin):
    """决策请求 Admin"""

    list_display = [
        "request_id",
        "asset_code",
        "asset_class",
        "direction",
        "priority",
        "requested_at",
    ]

    list_filter = [
        "priority",
        "requested_at",
    ]

    search_fields = [
        "request_id",
        "asset_code",
    ]
