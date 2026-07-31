from django.apps import AppConfig


class SentimentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sentiment"
    verbose_name = "舆情情感分析"

    def ready(self) -> None:
        """Import tasks module when app is ready"""
        import apps.sentiment.application.tasks  # noqa: F401 - Import Celery tasks
        from apps.sentiment.application.pulse_facade import get_sentiment_pulse_series
        from shared.infrastructure.decision_safe_series_registry import (
            register_sentiment_series_loader,
        )

        register_sentiment_series_loader(get_sentiment_pulse_series)
