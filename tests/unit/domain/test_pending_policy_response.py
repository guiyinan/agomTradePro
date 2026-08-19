"""Regression coverage for persisted, not-yet-classified policy events."""

from apps.policy.domain.entities import PolicyLevel
from apps.policy.domain.rules import MarketAction, get_policy_response


def test_pending_level_has_safe_review_response() -> None:
    """Pending events have a safe response instead of crashing status reads."""

    response = get_policy_response(PolicyLevel.PENDING)

    assert response.level is PolicyLevel.PENDING
    assert response.market_action is MarketAction.NORMAL_OPERATION
    assert response.cash_adjustment == 0.0
    assert response.signal_pause_hours is None
    assert response.requires_manual_approval is True
    assert response.alert_triggered is True
