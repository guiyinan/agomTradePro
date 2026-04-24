"""
Execution Task Facade.

Extends the base snapshot with execution-specific context:
- Simulated trading account status
- Open positions detail
- Trading cost estimates
"""

import logging
from typing import Any

from apps.agent_runtime.application.facades.base import BaseContextFacade

logger = logging.getLogger(__name__)


class ExecutionTaskFacade(BaseContextFacade):
    """Facade for execution domain tasks."""

    domain = "execution"

    def fetch_portfolio_summary(self) -> dict[str, Any]:
        """Enhanced portfolio summary with position details for execution."""
        base = super().fetch_portfolio_summary()
        if base.get("status") != "ok":
            return base
        try:
            portfolio_id = base.get("portfolio_id")
            if portfolio_id:
                position_summary = self.context_repository.fetch_portfolio_position_summary(
                    portfolio_id
                )
                if position_summary.get("status") == "ok":
                    base["top_positions"] = position_summary.get("top_positions", [])
        except Exception as e:
            logger.debug("Position details unavailable: %s", e)
        return base

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Enhanced risk summary with beta gate test results."""
        base = super().fetch_risk_alerts_summary()
        try:
            account_summary = self.context_repository.fetch_simulated_account_summary()
            if account_summary.get("status") == "ok":
                base["active_simulated_accounts"] = account_summary.get(
                    "active_simulated_accounts",
                    0,
                )
        except Exception as e:
            logger.debug("Simulated accounts unavailable: %s", e)
        return base
