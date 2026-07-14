"""Django model autodiscovery bridge for realtime persistence."""

from apps.realtime.infrastructure.models import (  # noqa: F401
    PriceAlertModel,
    PriceSubscriptionModel,
)

__all__ = ["PriceAlertModel", "PriceSubscriptionModel"]
