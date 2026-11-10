"""Account action result scope shared by TUI execution and projection."""

from __future__ import annotations

_SCOPED_ACCOUNT_ACTIONS: frozenset[str] = frozenset(
    {
        "simulated-trading.orders",
        "simulated-trading.order-fills",
        "simulated-trading.order-decisions",
        "simulated-trading.order-decision-apply",
        "simulated-trading.order-cancel",
        "simulated-trading.order-match",
        "simulated-trading.order-preview",
        "simulated-trading.order-confirm",
        "simulated-trading.order-by-key",
        "simulated-trading.order-entry-orders",
        "rebalance-plan.order-confirm",
        "rebalance-plan.order-by-key",
        "simulated-trading.holding-disclosures",
    }
)


def requires_account_result_scope(action_key: str) -> bool:
    """Keep exact request scope, strict transport status and business outcomes."""

    return action_key in _SCOPED_ACCOUNT_ACTIONS
