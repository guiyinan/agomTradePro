"""Retired Tushare client namespace.

The provider transport is owned by
``apps.data_center.infrastructure.tushare_client``.  This module remains as
an explicit fail-closed tombstone so an un-migrated caller cannot silently
create a second provider client in ``shared``.
"""

from __future__ import annotations


class TushareRelayAuthorizationError(RuntimeError):
    """Raised when a retired shared-client import is used."""


def create_tushare_pro_client(*_args: object, **_kwargs: object) -> object:
    """Fail closed and direct callers to the Data Center provider boundary."""

    raise RuntimeError(
        "Tushare client moved to apps.data_center.infrastructure.tushare_client"
    )


def resolve_tushare_runtime_settings(*_args: object, **_kwargs: object) -> object:
    """Fail closed for the retired shared runtime settings entry point."""

    raise RuntimeError(
        "Tushare settings moved to apps.data_center.infrastructure.tushare_client"
    )


__all__ = [
    "TushareRelayAuthorizationError",
    "create_tushare_pro_client",
    "resolve_tushare_runtime_settings",
]
