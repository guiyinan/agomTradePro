"""Audit App Configuration"""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Audit Reports"

    def ready(self) -> None:
        """Import admin module when app is ready"""
        import apps.audit.interface.admin  # noqa: F401
        from apps.audit.application.account_gateway import register_audit_account_gateway
        from apps.audit.application.backtest_gateway import register_audit_backtest_gateway

        register_audit_account_gateway()
        register_audit_backtest_gateway()
