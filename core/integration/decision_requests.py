"""Decision request integration bridge."""

from typing import Any

from apps.decision_rhythm.infrastructure.repositories import (
    DecisionRequestRepository,
)


class DecisionRequestRepositoryWrapper:
    """Bridge events-side status writes onto the decision rhythm repository."""

    def __init__(self) -> None:
        self._actual_repo = DecisionRequestRepository()

    def update_execution_status_to_executed(
        self,
        request_id: str,
        execution_ref: dict[str, Any] | None,
    ) -> bool:
        return self._actual_repo.update_execution_status_to_executed(
            request_id,
            execution_ref,
        )

    def update_execution_status_to_failed(self, request_id: str) -> bool:
        return self._actual_repo.update_execution_status_to_failed(request_id)

    def get_by_id(self, request_id: str):
        return self._actual_repo.get_by_id(request_id)


def get_decision_request_repository() -> DecisionRequestRepositoryWrapper:
    """Return the shared bridge for decision request status writes."""
    return DecisionRequestRepositoryWrapper()
