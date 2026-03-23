"""
Execution Task Facade.

Extends the base snapshot with execution-specific context:
- Simulated trading account status
- Open positions detail
- Trading cost estimates
"""

import logging
from typing import Any, Dict

from apps.agent_runtime.application.facades.base import BaseContextFacade, _unavailable

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
            from apps.account.infrastructure.models import Position
            portfolio_id = base.get("portfolio_id")
            if portfolio_id:
                positions = list(
                    Position.objects.filter(
                        portfolio_id=portfolio_id, is_closed=False
                    ).values("asset_code", "shares", "avg_cost")[:10]
                )
                base["top_positions"] = positions
        except Exception as e:
            logger.debug("Position details unavailable: %s", e)
        return base

    def fetch_risk_alerts_summary(self) -> dict[str, Any]:
        """Enhanced risk summary with beta gate test results."""
        base = super().fetch_risk_alerts_summary()
        try:
            from apps.simulated_trading.infrastructure.models import SimulatedAccount
            active_accounts = SimulatedAccount.objects.filter(is_active=True).count()
            base["active_simulated_accounts"] = active_accounts
        except Exception as e:
            logger.debug("Simulated accounts unavailable: %s", e)
        return base
