"""Bridge helpers for decision-rhythm exit advisors."""

from apps.simulated_trading.application.ports import PositionExitAdvisorProtocol


def build_decision_rhythm_exit_advisor() -> PositionExitAdvisorProtocol:
    """Build the default exit advisor through the owning decision-rhythm module."""

    from apps.decision_rhythm.application.exit_advisors import (
        build_decision_rhythm_exit_advisor as _build_decision_rhythm_exit_advisor,
    )

    return _build_decision_rhythm_exit_advisor()
