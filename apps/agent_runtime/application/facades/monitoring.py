"""
Monitoring Task Facade.

Extends the base snapshot with monitoring-specific context:
- Real-time price alerts
- Sentiment gate status
- Data quality metrics
"""

import logging
from typing import Any, Dict

from apps.agent_runtime.application.facades.base import BaseContextFacade, _unavailable

logger = logging.getLogger(__name__)


class MonitoringTaskFacade(BaseContextFacade):
    """Facade for monitoring domain tasks."""

    domain = "monitoring"

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Enhanced risk summary with price alerts for monitoring."""
        base = super().fetch_risk_alerts_summary()
        # Add price alert counts
        try:
            from apps.realtime.infrastructure.models import PriceAlert
            active_alerts = PriceAlert.objects.filter(is_active=True).count()
            triggered_alerts = PriceAlert.objects.filter(
                is_active=True, is_triggered=True
            ).count()
            base["active_price_alerts"] = active_alerts
            base["triggered_price_alerts"] = triggered_alerts
        except Exception as e:
            logger.debug("Price alerts unavailable: %s", e)
        return base

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Enhanced freshness with sentiment and realtime data status."""
        base = super().fetch_data_freshness_summary()
        # Add sentiment freshness
        try:
            from apps.sentiment.infrastructure.models import SentimentRecord
            latest = SentimentRecord.objects.order_by("-created_at").first()
            if latest:
                base["sources"]["sentiment"] = latest.created_at.isoformat()
        except Exception:
            base.setdefault("sources", {})["sentiment"] = "unavailable"
        return base
