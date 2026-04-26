"""Share repository providers for application consumers."""

from apps.share.infrastructure.providers import ShareInterfaceRepository
from apps.share.infrastructure.orm_handles import (
    ShareLinkDoesNotExist,
    ShareSnapshotDoesNotExist,
    SimulatedAccountDoesNotExist,
    UserDoesNotExist,
    share_access_log_manager,
    share_link_manager,
    share_snapshot_manager,
    simulated_account_manager,
    user_manager,
)


def get_share_interface_repository() -> ShareInterfaceRepository:
    """Return the share interface repository."""

    return ShareInterfaceRepository()
