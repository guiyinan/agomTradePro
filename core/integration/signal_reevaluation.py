"""Bridge helpers for policy-triggered signal reevaluation."""

from __future__ import annotations

from apps.signal.application.repository_provider import get_signal_repository
from apps.signal.application.use_cases import (
    ReevaluateSignalsRequest,
    ReevaluateSignalsUseCase,
)


def reevaluate_signals_for_policy_change(
    *,
    policy_level: int,
    current_regime: str,
    regime_confidence: float,
):
    """Reevaluate active signals after a policy-level change."""

    signal_repo = get_signal_repository()
    use_case = ReevaluateSignalsUseCase(signal_repository=signal_repo)
    request = ReevaluateSignalsRequest(
        policy_level=policy_level,
        current_regime=current_regime,
        regime_confidence=regime_confidence,
    )
    return use_case.execute(request)
