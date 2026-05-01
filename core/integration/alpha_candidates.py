"""Alpha candidate bridge."""

from apps.alpha_trigger.infrastructure.repositories import (
    AlphaCandidateRepository,
)


class AlphaCandidateRepositoryWrapper:
    """Bridge events-side writes onto the alpha candidate repository."""

    def __init__(self) -> None:
        self._actual_repo = AlphaCandidateRepository()

    def update_last_decision_request_id(
        self,
        candidate_id: str,
        request_id: str,
    ) -> bool:
        return self._actual_repo.update_last_decision_request_id(
            candidate_id,
            request_id,
        )

    def update_status_to_rejected(self, candidate_id: str) -> bool:
        return self._actual_repo.update_status_to_rejected(candidate_id)

    def update_status_to_executed(self, candidate_id: str) -> bool:
        return self._actual_repo.update_status_to_executed(candidate_id)

    def update_execution_status_to_failed(self, candidate_id: str) -> bool:
        return self._actual_repo.update_execution_status_to_failed(candidate_id)

    def get_by_asset(self, asset_code: str):
        """Return alpha candidates for one asset code."""

        return self._actual_repo.get_by_asset(asset_code)

    def get_actionable(self):
        """Return actionable alpha candidates."""

        return self._actual_repo.get_actionable()


def get_alpha_candidate_repository() -> AlphaCandidateRepositoryWrapper:
    """Return the shared bridge for alpha candidate status writes."""
    return AlphaCandidateRepositoryWrapper()
