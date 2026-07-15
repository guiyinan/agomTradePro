"""Share repository providers for application consumers."""

from __future__ import annotations

from apps.share.domain.interfaces import (
    ShareApplicationRepositoryProtocol,
    ShareInterfaceRepositoryProtocol,
)
from apps.share.infrastructure.providers import (
    ShareApplicationRepository,
    ShareInterfaceRepository,
)

from .account_gateway import get_share_account_gateway


def get_share_application_repository() -> ShareApplicationRepositoryProtocol:
    """Return the share application repository implementation."""

    return ShareApplicationRepository(account_gateway=get_share_account_gateway())


def get_share_interface_repository() -> ShareInterfaceRepositoryProtocol:
    """Return the share interface repository implementation."""

    return ShareInterfaceRepository(account_gateway=get_share_account_gateway())
