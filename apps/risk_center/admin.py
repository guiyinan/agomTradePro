"""Django admin registration for risk center."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskDailyReportModel,
    RiskExceptionModel,
    RiskPolicyAuditModel,
    RiskTemplateModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(GlobalRiskFloorModel)
class GlobalRiskFloorAdmin(TypedModelAdmin[GlobalRiskFloorModel]):
    list_display = (
        "name",
        "is_active",
        "max_total_position_pct",
        "max_single_position_pct",
        "updated_at",
    )
    list_filter = ("is_active",)


@admin.register(RiskTemplateModel)
class RiskTemplateAdmin(TypedModelAdmin[RiskTemplateModel]):
    list_display = ("key", "name", "risk_profile", "is_active", "updated_at")
    list_filter = ("risk_profile", "is_active")
    search_fields = ("key", "name")


@admin.register(AccountRiskPolicyModel)
class AccountRiskPolicyAdmin(TypedModelAdmin[AccountRiskPolicyModel]):
    list_display = ("account_id", "template", "risk_profile", "is_active", "updated_at")
    list_filter = ("risk_profile", "is_active")
    search_fields = ("account_id",)


@admin.register(RiskExceptionModel)
class RiskExceptionAdmin(TypedModelAdmin[RiskExceptionModel]):
    list_display = ("field_name", "account_id", "is_active", "expires_at", "created_by")
    list_filter = ("field_name", "is_active")
    search_fields = ("field_name", "reason")


@admin.register(RiskPolicyAuditModel)
class RiskPolicyAuditAdmin(TypedModelAdmin[RiskPolicyAuditModel]):
    list_display = ("target_type", "target_id", "action", "actor", "created_at")
    list_filter = ("target_type", "action")
    search_fields = ("target_id", "reason")
    readonly_fields = (
        "target_type",
        "target_id",
        "action",
        "actor",
        "before",
        "after",
        "reason",
        "created_at",
    )

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RiskPolicyAuditModel | None = None,
    ) -> bool:
        """Keep M1 audit evidence visible but deny its per-row admin deletion."""

        if obj is not None and obj.target_type == RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION:
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[RiskPolicyAuditModel],
    ) -> None:
        """Reject mixed bulk deletion containing any M1 publication or revoke event."""

        if queryset.filter(target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION).exists():
            raise PermissionDenied("M1 risk policy audit events cannot be deleted.")
        super().delete_queryset(request, queryset)


@admin.register(RiskDailyReportModel)
class RiskDailyReportAdmin(TypedModelAdmin[RiskDailyReportModel]):
    list_display = ("account_id", "report_date", "status", "generated_by", "updated_at")
    list_filter = ("status", "report_date")
    search_fields = ("account_id",)
    readonly_fields = (
        "account_id",
        "report_date",
        "status",
        "risk_daily_report",
        "position_daily_report",
        "post_investment_check",
        "input_snapshot",
        "generated_by",
        "created_at",
        "updated_at",
    )
