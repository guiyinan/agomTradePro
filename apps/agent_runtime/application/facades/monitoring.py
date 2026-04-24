"""
Monitoring Task Facade.

Extends the base snapshot with monitoring-specific context:
- Real-time price alerts
- Sentiment gate status
- Data quality metrics
"""

import logging
from typing import Any

from apps.agent_runtime.application.facades.base import BaseContextFacade

logger = logging.getLogger(__name__)


class MonitoringTaskFacade(BaseContextFacade):
    """Facade for monitoring domain tasks."""

    domain = "monitoring"

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Enhanced risk summary with price alerts for monitoring."""
        base = super().fetch_risk_alerts_summary()
        try:
            alert_summary = self.context_repository.fetch_price_alert_summary()
            if alert_summary.get("status") == "ok":
                base["active_price_alerts"] = alert_summary.get("active_price_alerts", 0)
                base["triggered_price_alerts"] = alert_summary.get(
                    "triggered_price_alerts",
                    0,
                )
        except Exception as e:
            logger.debug("Price alerts unavailable: %s", e)
        return base

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Enhanced freshness with sentiment and realtime data status."""
        base = super().fetch_data_freshness_summary()
        try:
            sentiment_summary = self.context_repository.fetch_sentiment_freshness_summary()
            if sentiment_summary.get("status") == "ok":
                base.setdefault("sources", {})["sentiment"] = sentiment_summary.get(
                    "sentiment"
                )
            elif sentiment_summary.get("status") == "no_data":
                base.setdefault("sources", {})["sentiment"] = "no_data"
            else:
                base.setdefault("sources", {})["sentiment"] = "unavailable"
        except Exception:
            base.setdefault("sources", {})["sentiment"] = "unavailable"
        return base
