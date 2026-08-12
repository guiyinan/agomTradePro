"""Django application configuration for broker execution."""

from django.apps import AppConfig


class BrokerExecutionConfig(AppConfig):
    """Register broker-execution infrastructure providers."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.broker_execution"
    verbose_name = "实盘执行中心"

    def ready(self) -> None:
        """Configure the default repository at the composition root."""

        from apps.broker_execution.application.repository_provider import (
            configure_broker_execution_repository,
        )
        from apps.broker_execution.infrastructure import security_signals
        from apps.broker_execution.infrastructure.repositories import (
            DjangoBrokerExecutionRepository,
        )
        from apps.broker_execution.r8_monitoring_reconciliation_composition import (
            build_django_r8_broker_monitoring_receipt_provider,
        )
        from core.integration.r8_broker_monitoring import (
            configure_r8_broker_monitoring_factory,
        )

        configure_broker_execution_repository(DjangoBrokerExecutionRepository)
        configure_r8_broker_monitoring_factory(
            lambda using: build_django_r8_broker_monitoring_receipt_provider(using=using)
        )
        _ = security_signals
