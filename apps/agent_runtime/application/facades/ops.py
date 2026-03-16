"""
Ops Task Facade.

Extends the base snapshot with ops-specific context:
- System health (celery, event bus)
- Audit summary
- Data quality metrics
"""

import logging
from typing import Any, Dict

from apps.agent_runtime.application.facades.base import BaseContextFacade, _unavailable

logger = logging.getLogger(__name__)


class OpsTaskFacade(BaseContextFacade):
    """Facade for ops domain tasks."""

    domain = "ops"

    def fetch_task_health_summary(self) -> Dict[str, Any]:
        """Enhanced task health with event bus status."""
        base = super().fetch_task_health_summary()
        # Add event bus metrics
        try:
            from apps.events.infrastructure.models import EventRecord
            total_events = EventRecord.objects.count()
            base["total_event_records"] = total_events
        except Exception as e:
            logger.debug("Event bus metrics unavailable: %s", e)
        return base

    def fetch_data_freshness_summary(self) -> Dict[str, Any]:
        """Enhanced freshness with audit and AI provider status."""
        base = super().fetch_data_freshness_summary()
        # Add AI provider status
        try:
            from apps.ai_provider.infrastructure.models import AIProvider
            active_providers = AIProvider.objects.filter(is_active=True).count()
            base["sources"]["ai_providers_active"] = active_providers
        except Exception:
            base.setdefault("sources", {})["ai_providers"] = "unavailable"
        # Add audit freshness
        try:
            from apps.audit.infrastructure.models import AuditRecord
            latest_audit = AuditRecord.objects.order_by("-created_at").first()
            if latest_audit:
                base["sources"]["audit"] = latest_audit.created_at.isoformat()
        except Exception:
            base.setdefault("sources", {})["audit"] = "unavailable"
        return base
