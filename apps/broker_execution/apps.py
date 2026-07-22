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

        configure_broker_execution_repository(DjangoBrokerExecutionRepository)
        _ = security_signals
