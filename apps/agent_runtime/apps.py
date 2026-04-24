"""Agent Runtime App Configuration"""

from django.apps import AppConfig


class AgentRuntimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.agent_runtime"
    verbose_name = "Agent Runtime"

    def ready(self):
        """Import modules when app is ready"""
        from .application.config_summary_service import (
            configure_agent_runtime_config_summary_repository,
        )
        from .infrastructure.config_summary_repository import (
            DjangoAgentRuntimeConfigSummaryRepository,
        )

        configure_agent_runtime_config_summary_repository(
            DjangoAgentRuntimeConfigSummaryRepository()
        )
