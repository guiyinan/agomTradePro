"""
Decision Rhythm Django Admin Configuration

决策频率约束和配额管理的 Django Admin 配置。
"""

from django.contrib import admin
from django.http import HttpRequest

from apps.decision_rhythm.models import (
    CooldownPeriodModel,
    DecisionModelParamAuditLogModel,
    DecisionModelParamConfigModel,
    DecisionQuotaModel,
    DecisionRequestModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(DecisionQuotaModel)
class DecisionQuotaAdmin(TypedModelAdmin[DecisionQuotaModel]):
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
class CooldownPeriodAdmin(TypedModelAdmin[CooldownPeriodModel]):
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
class DecisionRequestAdmin(TypedModelAdmin[DecisionRequestModel]):
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


@admin.register(DecisionModelParamConfigModel)
class DecisionModelParamConfigAdmin(TypedModelAdmin[DecisionModelParamConfigModel]):
    """Manage validated model parameters without exposing audit evidence as editable."""

    list_display = ["param_key", "param_type", "env", "version", "is_active", "updated_at"]
    list_filter = ["env", "param_type", "is_active"]
    search_fields = ["param_key", "description", "updated_by"]
    readonly_fields = ["config_id", "created_at", "updated_at"]


@admin.register(DecisionModelParamAuditLogModel)
class DecisionModelParamAuditLogAdmin(TypedModelAdmin[DecisionModelParamAuditLogModel]):
    """Expose append-only parameter audit evidence as read-only."""

    list_display = ["param_key", "env", "changed_by", "changed_at"]
    list_filter = ["env", "changed_at"]
    search_fields = ["param_key", "changed_by", "change_reason"]
    readonly_fields = [
        "log_id",
        "param_key",
        "old_value",
        "new_value",
        "env",
        "changed_by",
        "change_reason",
        "changed_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require audit evidence to be created by the owning use case."""

        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: DecisionModelParamAuditLogModel | None = None,
    ) -> bool:
        """Keep existing audit evidence immutable in Admin."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DecisionModelParamAuditLogModel | None = None,
    ) -> bool:
        """Keep existing audit evidence undeletable in Admin."""

        return False
