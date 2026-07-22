from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.research"
    verbose_name = "Research Registry"

    def ready(self) -> None:
        from core.integration.research_integrity_registry import (
            configure_research_promotion_checker,
        )

        from .infrastructure.models import PromotionDecision

        configure_research_promotion_checker(
            lambda decision_id: PromotionDecision._default_manager.filter(
                decision_id=decision_id,
                decision="approved",
            ).exists()
        )
