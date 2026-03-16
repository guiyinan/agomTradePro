"""Agent Runtime App Configuration"""
from django.apps import AppConfig


class AgentRuntimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.agent_runtime'
    verbose_name = 'Agent Runtime'

    def ready(self):
        """Import modules when app is ready"""
        pass
