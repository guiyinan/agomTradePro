"""Alpha trigger bridge."""

from apps.alpha_trigger.infrastructure.repositories import (
    AlphaTriggerRepository,
)


class AlphaTriggerRepositoryWrapper:
    """Bridge read access onto the alpha trigger repository."""

    def __init__(self) -> None:
        self._actual_repo = AlphaTriggerRepository()

    def get_active(self, asset_code: str | None = None):
        """Return active alpha triggers."""

        return self._actual_repo.get_active(asset_code=asset_code)


def get_alpha_trigger_repository() -> AlphaTriggerRepositoryWrapper:
    """Return the shared bridge for alpha trigger reads."""

    return AlphaTriggerRepositoryWrapper()
