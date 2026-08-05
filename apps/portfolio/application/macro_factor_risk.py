"""Application boundary for R4 macro-factor candidate research."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.macro_factor_risk import (
    MacroRiskCandidateInput,
    MacroRiskCandidateReport,
    MacroRiskValidationPolicy,
    evaluate_macro_risk_candidate,
)


class MacroRiskCandidateProvider(Protocol):
    """Provide one canonical candidate assembled at the composition root."""

    def get_candidate(self, candidate_id: str) -> MacroRiskCandidateInput | None:
        """Return an immutable candidate or ``None`` when evidence is absent."""


class EvaluateMacroRiskCandidate:
    """Evaluate R4 evidence without authorizing publication or execution."""

    def __init__(
        self,
        provider: MacroRiskCandidateProvider,
        policy: MacroRiskValidationPolicy,
    ) -> None:
        self._provider = provider
        self._policy = policy

    def execute(
        self,
        *,
        candidate_id: str,
        evaluated_at: datetime,
    ) -> MacroRiskCandidateReport:
        """Return the auditable report; missing canonical input fails closed."""

        candidate = self._provider.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("canonical macro-risk candidate evidence is unavailable")
        return evaluate_macro_risk_candidate(
            candidate,
            policy=self._policy,
            evaluated_at=evaluated_at,
        )


__all__ = ["EvaluateMacroRiskCandidate", "MacroRiskCandidateProvider"]
