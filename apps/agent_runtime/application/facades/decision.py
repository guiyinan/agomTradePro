"""
Decision Task Facade.

Extends the base snapshot with decision-specific context:
- Decision rhythm quotas
- Pending approval counts
- Signal eligibility status
"""

import logging
from typing import Any

from apps.agent_runtime.application.facades.base import BaseContextFacade

logger = logging.getLogger(__name__)


class DecisionTaskFacade(BaseContextFacade):
    """Facade for decision domain tasks."""

    domain = "decision"

    def fetch_open_decisions_summary(self) -> dict[str, Any]:
        """Enhanced decision summary with quota information."""
        base = super().fetch_open_decisions_summary()
        try:
            quota_summary = self.context_repository.fetch_decision_quota_summary()
            if quota_summary.get("status") == "ok":
                base["quotas"] = quota_summary.get("quotas", [])
        except Exception as e:
            logger.debug("Decision quotas unavailable: %s", e)
        return base

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Enhanced signals with approval-pending signals count."""
        base = super().fetch_active_signals_summary()
        if base.get("status") != "ok":
            return base
        try:
            signal_summary = self.context_repository.fetch_pending_signal_summary()
            if signal_summary.get("status") == "ok":
                base["pending_approval"] = signal_summary.get("pending_approval", 0)
        except Exception:
            pass
        return base
