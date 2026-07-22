"""Research registry use cases."""

from __future__ import annotations

import uuid
from typing import Any, Protocol


class ResearchRegistryGateway(Protocol):
    def create_experiment(self, **kwargs: Any) -> Any: ...
    def create_trial(self, payload: dict[str, Any]) -> Any: ...
    def evaluate_promotion(self, trial_id: str) -> Any: ...


class RegisterExperiment:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(
        self, *, question: str, hypothesis: str, owner_id: int | None
    ) -> Any:
        """Register a research question and its falsifiable hypothesis."""

        return self._repository.create_experiment(
            experiment_id=uuid.uuid4().hex,
            question=question,
            hypothesis=hypothesis,
            owner_id=owner_id,
        )


class RunTrial:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(self, payload: dict[str, Any]) -> Any:
        """Freeze and register one trial payload."""

        payload = dict(payload)
        payload.setdefault("trial_id", uuid.uuid4().hex)
        return self._repository.create_trial(payload)


class EvaluatePromotion:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(self, trial_id: str) -> Any:
        """Evaluate a completed trial against the promotion gate."""

        return self._repository.evaluate_promotion(trial_id)
