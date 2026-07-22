"""Read-only Django Admin projections for governed broker execution."""

from django.contrib import admin

from apps.broker_execution.infrastructure.models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerExecutionDailyReportModel,
    LiveOrderModel,
    ReconciliationDifferenceModel,
    ReconciliationRunModel,
    TradingControlModel,
)


class ReadOnlyExecutionAdmin(admin.ModelAdmin):
    """Prevent Django Admin from bypassing governed execution use cases."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(BrokerAgentModel)
class BrokerAgentAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "agent_id",
        "display_name",
        "user",
        "status",
        "qmt_connected",
        "last_heartbeat_at",
        "is_active",
    )
    list_filter = ("status", "qmt_connected", "is_active")
    search_fields = ("agent_id", "display_name", "user__username")


@admin.register(BrokerAccountBindingModel)
class BrokerAccountBindingAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "account_id",
        "user",
        "agent",
        "broker_account_mask",
        "auto_execution_enabled",
        "is_active",
    )
    list_filter = ("auto_execution_enabled", "is_active", "account_type")
    exclude = ("broker_account_ref",)


@admin.register(BrokerAccountAccessModel)
class BrokerAccountAccessAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "user",
        "account_id",
        "can_approve",
        "can_trade",
        "is_active",
        "granted_by",
    )
    list_filter = ("can_approve", "can_trade", "is_active")


@admin.register(LiveOrderModel)
class LiveOrderAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "client_order_id",
        "account_id",
        "asset_code",
        "side",
        "quantity",
        "limit_price",
        "status",
        "updated_at",
    )
    list_filter = ("status", "side", "order_type")
    search_fields = ("client_order_id", "asset_code", "broker_order_id")
    readonly_fields = (
        "client_order_id",
        "approval_digest",
        "approved_at",
        "submitted_at",
        "created_at",
        "updated_at",
    )


@admin.register(ReconciliationRunModel)
class ReconciliationRunAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "id",
        "account_id",
        "status",
        "order_difference_count",
        "fill_difference_count",
        "cash_difference_count",
        "position_difference_count",
        "started_at",
    )
    list_filter = ("status",)


@admin.register(ReconciliationDifferenceModel)
class ReconciliationDifferenceAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "run",
        "dimension",
        "difference_key",
        "severity",
        "status",
        "created_at",
    )
    list_filter = ("dimension", "severity", "status")
    readonly_fields = tuple(
        field.name for field in ReconciliationDifferenceModel._meta.fields
    )


@admin.register(BrokerExecutionAlertModel)
class BrokerExecutionAlertAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "last_seen_at",
        "account_id",
        "severity",
        "code",
        "status",
        "auto_stop_applied",
    )
    list_filter = ("severity", "status", "auto_stop_applied")
    readonly_fields = tuple(
        field.name for field in BrokerExecutionAlertModel._meta.fields
    )


@admin.register(BrokerExecutionDailyReportModel)
class BrokerExecutionDailyReportAdmin(ReadOnlyExecutionAdmin):
    list_display = ("report_date", "account_id", "status", "generated_at")
    list_filter = ("status", "report_date")
    readonly_fields = tuple(
        field.name for field in BrokerExecutionDailyReportModel._meta.fields
    )


@admin.register(TradingControlModel)
class TradingControlAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "user",
        "account_id",
        "kill_switch_active",
        "changed_by",
        "changed_at",
    )
    list_filter = ("kill_switch_active",)


@admin.register(BrokerAgentCredentialModel)
class BrokerAgentCredentialAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "credential_id",
        "agent",
        "expires_at",
        "revoked_at",
        "created_at",
    )
    readonly_fields = (
        "credential_id",
        "secret_hash",
        "scopes",
        "allowed_account_ids",
        "created_by",
        "created_at",
    )


@admin.register(BrokerExecutionAuditModel)
class BrokerExecutionAuditAdmin(ReadOnlyExecutionAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "account_id",
        "resource_type",
        "resource_id",
        "request_id",
    )
    list_filter = ("action", "resource_type", "actor_type")
    search_fields = ("resource_id", "request_id", "reason", "actor__username")
    readonly_fields = tuple(
        field.name for field in BrokerExecutionAuditModel._meta.fields
    )
