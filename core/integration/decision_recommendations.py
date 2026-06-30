"""Decision recommendation read bridges."""

from __future__ import annotations

from typing import Any


class DecisionRecommendationPlanReader:
    """Read decision-rhythm execution plans through a lazy integration bridge."""

    def __init__(self, recommendation_repo: Any | None = None) -> None:
        self._recommendation_repo = recommendation_repo

    @property
    def recommendation_repo(self) -> Any:
        """Return the owning decision-rhythm repository."""

        if self._recommendation_repo is None:
            from apps.decision_rhythm.application.repository_provider import (
                get_unified_recommendation_repository,
            )

            self._recommendation_repo = get_unified_recommendation_repository()
        return self._recommendation_repo

    def get_execution_plan_for_transaction(self, transaction_id: int) -> dict[str, Any] | None:
        """Return the execution plan matched to an imported transaction."""

        return self.recommendation_repo.get_execution_plan_for_transaction(transaction_id)


def build_decision_recommendation_plan_reader() -> DecisionRecommendationPlanReader:
    """Build the default decision recommendation plan reader."""

    return DecisionRecommendationPlanReader()
