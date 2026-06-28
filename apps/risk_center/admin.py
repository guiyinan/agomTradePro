"""Django admin registration for risk center."""

from django.apps import apps as django_apps
from django.contrib import admin

GlobalRiskFloorModel = django_apps.get_model("risk_center", "GlobalRiskFloorModel")
RiskTemplateModel = django_apps.get_model("risk_center", "RiskTemplateModel")
AccountRiskPolicyModel = django_apps.get_model("risk_center", "AccountRiskPolicyModel")
RiskExceptionModel = django_apps.get_model("risk_center", "RiskExceptionModel")
RiskPolicyAuditModel = django_apps.get_model("risk_center", "RiskPolicyAuditModel")
RiskDailyReportModel = django_apps.get_model("risk_center", "RiskDailyReportModel")


@admin.register(GlobalRiskFloorModel)
class GlobalRiskFloorAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "max_total_position_pct",
        "max_single_position_pct",
        "updated_at",
    )
    list_filter = ("is_active",)


@admin.register(RiskTemplateModel)
class RiskTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "risk_profile", "is_active", "updated_at")
    list_filter = ("risk_profile", "is_active")
    search_fields = ("key", "name")


@admin.register(AccountRiskPolicyModel)
class AccountRiskPolicyAdmin(admin.ModelAdmin):
    list_display = ("account_id", "template", "risk_profile", "is_active", "updated_at")
    list_filter = ("risk_profile", "is_active")
    search_fields = ("account_id",)


@admin.register(RiskExceptionModel)
class RiskExceptionAdmin(admin.ModelAdmin):
    list_display = ("field_name", "account_id", "is_active", "expires_at", "created_by")
    list_filter = ("field_name", "is_active")
    search_fields = ("field_name", "reason")


@admin.register(RiskPolicyAuditModel)
class RiskPolicyAuditAdmin(admin.ModelAdmin):
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
class RiskDailyReportAdmin(admin.ModelAdmin):
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
