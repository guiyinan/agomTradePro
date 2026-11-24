"""
Core Django App Configuration

This is mainly for template tags and other core functionality.
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        """Register core production-readiness checks."""

        from core import checks  # noqa: F401

        if self.apps is not None and self.apps.is_installed("apps.broker_execution"):
            from apps.broker_execution.order_checkpoint_composition import (
                register_order_checkpoint_reader,
            )
            from core.integration.broker_signed_order_checkpoint import read_signed_checkpoint

            register_order_checkpoint_reader(read_signed_checkpoint)

        if self.apps is not None and self.apps.is_installed("apps.portfolio"):
            from apps.portfolio.application.benchmark_daily_sources import (
                register_benchmark_day_sources,
            )
            from core.integration.portfolio_benchmark_daily_sources import (
                build_benchmark_day_sources,
            )

            register_benchmark_day_sources(build_benchmark_day_sources)

        if self.apps is not None and self.apps.is_installed("apps.broker_execution"):
            from apps.broker_execution.application.order_scope_sources import (
                install_order_scope_sources,
            )
            from core.integration.broker_order_scope_sources import build_order_scope_sources

            install_order_scope_sources(build_order_scope_sources)
