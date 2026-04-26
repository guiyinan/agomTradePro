"""Sector repository provider for application consumers."""

from __future__ import annotations

from apps.sector.infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter
from apps.sector.infrastructure.providers import DjangoSectorRepository


def get_sector_repository() -> DjangoSectorRepository:
    """Return the default sector repository."""

    return DjangoSectorRepository()


def get_sector_adapter() -> AKShareSectorAdapter:
    """Return the default sector adapter."""

    return AKShareSectorAdapter()
