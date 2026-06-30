"""Alpha trigger bridge."""

from apps.alpha_trigger.application.repository_provider import (
    get_alpha_trigger_repository as _get_alpha_trigger_repository,
)


class AlphaTriggerRepositoryWrapper:
    """Bridge read access onto the alpha trigger repository."""

    def __init__(self) -> None:
        self._actual_repo = _get_alpha_trigger_repository()

    def get_active(self, asset_code: str | None = None):
        """Return active alpha triggers."""

        return self._actual_repo.get_active(asset_code=asset_code)


def get_alpha_trigger_repository() -> AlphaTriggerRepositoryWrapper:
    """Return the shared bridge for alpha trigger reads."""

    return AlphaTriggerRepositoryWrapper()
