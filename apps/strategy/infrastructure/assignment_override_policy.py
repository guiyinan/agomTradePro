"""Fail-closed handling for strategy assignment risk overrides."""

from __future__ import annotations

import logging
from typing import Literal

from apps.strategy.infrastructure.models import (
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
)

logger = logging.getLogger(__name__)


def account_rule_binding_status(
    rule: PositionManagementRuleModel,
    account_id: int,
) -> Literal["unbound", "current", "other", "invalid"]:
    """Classify an explicit rule account binding without coercing JSON values."""

    metadata = getattr(rule, "metadata", None)
    if not isinstance(metadata, dict):
        return "invalid"
    if "account_id" not in metadata:
        return "unbound"
    value = metadata["account_id"]
    if type(value) is int:
        if value <= 0:
            return "invalid"
        return "current" if value == account_id else "other"
    if type(value) is str:
        if not value or not value.isascii() or not value.isdecimal() or value.startswith("0"):
            return "invalid"
        return "current" if value == str(account_id) else "other"
    return "invalid"


def assignment_has_unsupported_risk_override(
    assignment: PortfolioStrategyAssignmentModel | None,
) -> bool:
    """Reject active assignment overrides until their effective risk policy is modeled."""

    if assignment is None or assignment.is_active is not True:
        return False
    if assignment.override_max_position_pct is None and assignment.override_stop_loss_pct is None:
        return False
    logger.warning(
        "STRATEGY_ASSIGNMENT_OVERRIDE_UNSUPPORTED portfolio_id=%s strategy_id=%s",
        assignment.portfolio_id,
        assignment.strategy_id,
    )
    return True
