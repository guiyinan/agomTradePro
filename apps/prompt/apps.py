from django.apps import AppConfig


class PromptConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.prompt"
    verbose_name = "Prompt Management"

    def ready(self) -> None:
        from core.integration.research_integrity_registry import (
            configure_active_prompt_checker,
        )

        from .infrastructure.eval_models import PromptVersion

        configure_active_prompt_checker(
            lambda version_id: PromptVersion._default_manager.filter(
                version_id=version_id,
                status="active",
            ).exists()
        )
