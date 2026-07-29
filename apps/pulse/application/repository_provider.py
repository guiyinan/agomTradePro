"""Pulse repository providers for application consumers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from apps.pulse.application.dtos import PulseHistoryDTO
from apps.pulse.domain.entities import PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.providers import (
    NavigatorAssetConfigRepository,
    build_navigator_asset_config_repository,
    build_pulse_data_provider,
    build_pulse_repository,
)


class PulseRepositoryProtocol(Protocol):
    """Persistence operations required by Pulse Application use cases."""

    def save_snapshot(self, snapshot: PulseSnapshot) -> object:
        """Persist a calculated Pulse snapshot."""

        ...

    def get_latest_snapshot(self) -> PulseSnapshot | None:
        """Return the latest persisted Pulse snapshot."""

        ...

    def get_history(
        self,
        months: int = 6,
        limit: int | None = None,
    ) -> Sequence[PulseHistoryDTO]:
        """Return persisted history projections without exposing ORM semantics."""

        ...


class PulseDataProviderProtocol(Protocol):
    """Indicator-reading operations required by Pulse calculation."""

    def get_all_readings(self, as_of_date: date) -> list[PulseIndicatorReading]:
        """Return all Pulse inputs available at the requested date."""

        ...


def get_pulse_repository() -> PulseRepositoryProtocol:
    """Return the default pulse repository."""

    return build_pulse_repository()


def get_pulse_data_provider() -> PulseDataProviderProtocol:
    """Return the default pulse data provider."""

    return build_pulse_data_provider()


def get_navigator_asset_config_repository() -> NavigatorAssetConfigRepository:
    """Return the navigator asset-config repository used by regime navigation."""

    return build_navigator_asset_config_repository()
