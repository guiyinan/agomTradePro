"""Budgeted prompt evaluation and activation gates."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol


class PromptEvaluationGateway(Protocol):
    def record_run(self, payload: dict[str, Any]) -> Any: ...
    def promote(self, version_id: str) -> Any: ...


class RunPromptEvaluation:
    """Record deterministic assertions and stop at configured budgets."""

    def __init__(self, repository: PromptEvaluationGateway):
        self._repository = repository

    def execute(self, payload: dict[str, Any]) -> Any:
        """Validate budgets and record a deterministic evaluation run."""

        if payload["evaluation_type"] == "online" and float(payload.get("temperature", 0)) != 0:
            raise ValueError("online candidate evaluations require temperature=0")
        if payload["evaluation_type"] == "online" and (
            not payload.get("provider") or not payload.get("model")
        ):
            raise ValueError("online candidate evaluations require fixed provider and model")
        if Decimal(str(payload["max_cost"])) <= 0 or int(payload["max_tokens"]) <= 0:
            raise ValueError("evaluation budgets must be positive")
        return self._repository.record_run(payload)


class PromotePromptVersion:
    """Activate only versions with passing offline and online evidence."""

    def __init__(self, repository: PromptEvaluationGateway):
        self._repository = repository

    def execute(self, version_id: str) -> Any:
        """Promote a prompt version only when its gate evidence passes."""

        return self._repository.promote(version_id)
