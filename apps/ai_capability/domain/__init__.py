from django.apps import AppConfig


class AiCapabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_capability"
    verbose_name = "AI Capability Catalog"

    def ready(self):
        pass
