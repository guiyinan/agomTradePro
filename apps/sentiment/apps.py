from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from django.apps import AppConfig

from shared.infrastructure.decision_safe_series_registry import (
    register_sentiment_series_loader,
)

if TYPE_CHECKING:
    from apps.sentiment.application.pulse_facade import SentimentPulseSeriesResult


def _load_sentiment_series(
    *,
    as_of_date: date,
    lookback_days: int,
) -> SentimentPulseSeriesResult:
    """Adapt the Sentiment facade to the shared Pulse loader contract."""

    from apps.sentiment.application.pulse_facade import get_sentiment_pulse_series

    return get_sentiment_pulse_series(
        as_of_date=as_of_date,
        lookback_days=lookback_days,
    )


class SentimentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sentiment"
    verbose_name = "舆情情感分析"

    def ready(self) -> None:
        """Import tasks module when app is ready"""
        import apps.sentiment.application.tasks  # noqa: F401 - Import Celery tasks

        register_sentiment_series_loader(_load_sentiment_series)
