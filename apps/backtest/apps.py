"""Backtest App Configuration"""

from django.apps import AppConfig


class BacktestConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.backtest"
    verbose_name = "Backtest Engine"

    def ready(self) -> None:
        """Import admin and tasks modules when app is ready"""
        import apps.backtest.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.backtest.interface.admin  # noqa: F401
        from apps.backtest.application.account_gateway import register_backtest_account_gateway

        register_backtest_account_gateway()
        from core.integration.research_integrity_registry import (
            configure_backtest_evidence_getter,
        )

        from .infrastructure.models import BacktestResultModel

        def backtest_evidence(backtest_id: int):  # type: ignore[no-untyped-def]
            row = BacktestResultModel._default_manager.filter(pk=backtest_id).first()
            if row is None:
                return None
            return {
                "status": row.status,
                "trust_status": row.trust_status,
                "data_manifest_id": row.data_manifest_id,
                "research_trial_id": row.research_trial_id,
            }

        configure_backtest_evidence_getter(backtest_evidence)
