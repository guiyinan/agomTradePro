"""
Decision Task Facade.

Extends the base snapshot with decision-specific context:
- Decision rhythm quotas
- Pending approval counts
- Signal eligibility status
"""

import logging
from typing import Any, Dict

from apps.agent_runtime.application.facades.base import BaseContextFacade, _unavailable

logger = logging.getLogger(__name__)


class DecisionTaskFacade(BaseContextFacade):
    """Facade for decision domain tasks."""

    domain = "decision"

    def fetch_open_decisions_summary(self) -> dict[str, Any]:
        """Enhanced decision summary with quota information."""
        base = super().fetch_open_decisions_summary()
        # Add quota information
        try:
            from apps.decision_rhythm.infrastructure.models import DecisionQuota
            quotas = list(
                DecisionQuota.objects.values("decision_type", "max_count", "current_count")[:10]
            )
            base["quotas"] = quotas
        except Exception as e:
            logger.debug("Decision quotas unavailable: %s", e)
        return base

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Enhanced signals with approval-pending signals count."""
        base = super().fetch_active_signals_summary()
        if base.get("status") != "ok":
            return base
        try:
            from apps.signal.infrastructure.models import InvestmentSignal
            pending = InvestmentSignal.objects.filter(
                is_active=True, status="pending_approval"
            ).count()
            base["pending_approval"] = pending
        except Exception:
            pass
        return base
