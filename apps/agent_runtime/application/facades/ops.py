"""
Ops Task Facade.

Extends the base snapshot with ops-specific context:
- System health (celery, event bus)
- Audit summary
- Data quality metrics
"""

import logging
from typing import Any

from apps.agent_runtime.application.facades.base import BaseContextFacade

logger = logging.getLogger(__name__)


class OpsTaskFacade(BaseContextFacade):
    """Facade for ops domain tasks."""

    domain = "ops"

    def fetch_task_health_summary(self) -> dict[str, Any]:
        """Enhanced task health with event bus status."""
        base = super().fetch_task_health_summary()
        try:
            event_bus = self.context_repository.fetch_event_bus_summary()
            if event_bus.get("status") == "ok":
                base["total_event_records"] = event_bus.get("total_event_records", 0)
        except Exception as e:
            logger.debug("Event bus metrics unavailable: %s", e)
        return base

    def fetch_data_freshness_summary(self) -> dict[str, Any]:
        """Enhanced freshness with audit and AI provider status."""
        base = super().fetch_data_freshness_summary()
        try:
            provider_summary = self.context_repository.fetch_ai_provider_summary()
            if provider_summary.get("status") == "ok":
                base.setdefault("sources", {})["ai_providers_active"] = provider_summary.get(
                    "ai_providers_active", 0
                )
            else:
                base.setdefault("sources", {})["ai_providers"] = "unavailable"
        except Exception:
            base.setdefault("sources", {})["ai_providers"] = "unavailable"
        try:
            audit_summary = self.context_repository.fetch_audit_freshness_summary()
            if audit_summary.get("status") == "ok":
                base.setdefault("sources", {})["audit"] = audit_summary.get("audit")
            elif audit_summary.get("status") == "no_data":
                base.setdefault("sources", {})["audit"] = "no_data"
            else:
                base.setdefault("sources", {})["audit"] = "unavailable"
        except Exception:
            base.setdefault("sources", {})["audit"] = "unavailable"
        return base
