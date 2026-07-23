"""Django admin registration for risk center."""

from django.contrib import admin

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
