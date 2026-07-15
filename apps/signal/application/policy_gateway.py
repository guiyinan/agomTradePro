"""Register Signal reevaluation for Policy consumers."""

from __future__ import annotations

from typing import Any

from apps.policy.application.signal_gateway import register_signal_reevaluator

from . import repository_provider, use_cases


def _reevaluate_signals(
    *,
    policy_level: int,
    current_regime: str,
    regime_confidence: float,
) -> Any:
    signal_repo = repository_provider.get_signal_repository()
    use_case = use_cases.ReevaluateSignalsUseCase(signal_repository=signal_repo)
    request = use_cases.ReevaluateSignalsRequest(
        policy_level=policy_level,
        current_regime=current_regime,
        regime_confidence=regime_confidence,
    )
    return use_case.execute(request)


def register_signal_policy_gateway() -> None:
    """Register Signal reevaluation for Policy."""

    register_signal_reevaluator(_reevaluate_signals)


__all__ = ["register_signal_policy_gateway"]
