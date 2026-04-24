"""
Research Task Facade.

Extends the base snapshot with research-specific context:
- Deeper macro data (indicator trends)
- Sector analysis overview
- Alpha factor scores
"""

import logging
from typing import Any

from apps.agent_runtime.application.facades.base import BaseContextFacade

logger = logging.getLogger(__name__)


class ResearchTaskFacade(BaseContextFacade):
    """Facade for research domain tasks."""

    domain = "research"

    def fetch_regime_summary(self) -> dict[str, Any]:
        """Enhanced regime summary with trend context for research."""
        base = super().fetch_regime_summary()
        if base.get("status") != "ok":
            return base
        try:
            history_summary = self.context_repository.fetch_regime_history_summary()
            if history_summary.get("status") == "ok":
                base["history_records"] = history_summary.get("history_records", 0)
        except Exception:
            pass
        return base

    def fetch_active_signals_summary(self) -> dict[str, Any]:
        """Enhanced signals with invalidation status for research review."""
        base = super().fetch_active_signals_summary()
        if base.get("status") != "ok":
            return base
        try:
            signal_summary = self.context_repository.fetch_signal_invalidation_summary()
            if signal_summary.get("status") == "ok":
                base["with_invalidation_logic"] = signal_summary.get(
                    "with_invalidation_logic",
                    0,
                )
        except Exception:
            pass
        return base
