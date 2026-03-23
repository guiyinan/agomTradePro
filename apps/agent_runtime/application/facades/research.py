"""
Research Task Facade.

Extends the base snapshot with research-specific context:
- Deeper macro data (indicator trends)
- Sector analysis overview
- Alpha factor scores
"""

import logging
from typing import Any, Dict

from apps.agent_runtime.application.facades.base import BaseContextFacade, _unavailable

logger = logging.getLogger(__name__)


class ResearchTaskFacade(BaseContextFacade):
    """Facade for research domain tasks."""

    domain = "research"

    def fetch_regime_summary(self) -> dict[str, Any]:
        """Enhanced regime summary with trend context for research."""
        base = super().fetch_regime_summary()
        if base.get("status") != "ok":
            return base
        # Add regime history count for research context
        try:
            from apps.regime.infrastructure.models import RegimeRecord
            history_count = RegimeRecord.objects.count()
            base["history_records"] = history_count
        except Exception:
            pass
        return base

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Enhanced signals with invalidation status for research review."""
        base = super().fetch_active_signals_summary()
        if base.get("status") != "ok":
            return base
        try:
            from apps.signal.infrastructure.models import InvestmentSignal
            approaching_invalidation = InvestmentSignal.objects.filter(
                is_active=True,
            ).exclude(invalidation_logic="").count()
            base["with_invalidation_logic"] = approaching_invalidation
        except Exception:
            pass
        return base
