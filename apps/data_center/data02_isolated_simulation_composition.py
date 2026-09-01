"""Application-root composition for isolated DATA-02 historical simulation."""

from __future__ import annotations

from apps.data_center.application.data02_isolated_simulation import (
    Data02IsolatedSimulationCandidate,
    Data02IsolatedSimulationRequest,
    RunData02IsolatedSimulationUseCase,
)
from apps.data_center.infrastructure.data02_isolated_snapshot import (
    PostgresData02HistoricalSnapshotAdapter,
)


def make_data02_isolated_simulation_use_case(
    *, database_url: str
) -> RunData02IsolatedSimulationUseCase:
    """Build the DATA-02 simulation use case for one isolated PostgreSQL database."""

    return RunData02IsolatedSimulationUseCase(
        snapshot_port=PostgresData02HistoricalSnapshotAdapter(database_url=database_url)
    )


__all__ = [
    "Data02IsolatedSimulationCandidate",
    "Data02IsolatedSimulationRequest",
    "make_data02_isolated_simulation_use_case",
]
