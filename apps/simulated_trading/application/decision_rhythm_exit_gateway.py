"""Consumer-owned gateway for Decision Rhythm exit advice."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from .ports import PositionExitAdvice, PositionExitAdvisorProtocol

_builder: Callable[[], PositionExitAdvisorProtocol] | None = None


class _NoOpPositionExitAdvisor:
    """Safe fallback when the optional Decision Rhythm provider is absent."""

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]:
        """Return no automatic exit advice without an owning provider."""

        return []


def register_decision_rhythm_exit_advisor_builder(
    builder: Callable[[], PositionExitAdvisorProtocol],
) -> None:
    """Register the builder backed by Decision Rhythm outputs."""

    global _builder
    _builder = builder


def build_decision_rhythm_exit_advisor() -> PositionExitAdvisorProtocol:
    """Build the registered exit advisor or a side-effect-free fallback."""

    if _builder is None:
        return _NoOpPositionExitAdvisor()
    return _builder()


__all__ = [
    "build_decision_rhythm_exit_advisor",
    "register_decision_rhythm_exit_advisor_builder",
]
