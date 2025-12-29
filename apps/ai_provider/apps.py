"""AI Provider Django App Configuration."""
from django.apps import AppConfig


class AIProviderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ai_provider'
    verbose_name = 'AI Provider Management'

    def ready(self):
        """Import admin module when app is ready"""
        import apps.ai_provider.interface.admin  # noqa: F401
