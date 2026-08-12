from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.research"
    verbose_name = "Research Registry"

    def ready(self) -> None:
        from core.integration.r1_forecast_trial_evidence import (
            configure_r1_forecast_trial_evidence_factory,
        )
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
        from .r1_forecast_trial_evidence_composition import (
            build_r1_forecast_trial_evidence_provider,
        )

        configure_r1_forecast_trial_evidence_factory(
            lambda using: build_r1_forecast_trial_evidence_provider(using=using)
        )
