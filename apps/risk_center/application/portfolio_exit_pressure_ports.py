"""Injected dependencies for the account-scoped Scenario pressure use case."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.risk_center.application.portfolio_exit_pressure_dtos import PortfolioPressureProjection
from apps.risk_center.application.scenario_dtos import ScenarioRunRequestDTO
from apps.risk_center.application.scenario_impact_context import ScenarioImpactContext


class PortfolioPressureProjectionProviderProtocol(Protocol):
    """Read one owner-locked simulated-account projection and source bundle."""

    def get_pressure_projection(
        self,
        *,
        actor_user_id: int,
        account_id: int,
        scenario_revision_id: str,
        as_of_time: datetime,
    ) -> PortfolioPressureProjection | None:
        """Return one exact snapshot, policy, position, and capacity projection."""
        ...


class ScenarioPressurePreviewProtocol(Protocol):
    """Read one exact revision, snapshot, and market context without persistence."""

    def execute_with_context(self, request: ScenarioRunRequestDTO) -> ScenarioImpactContext:
        """Return the same source instances used for the impact calculation."""
        ...


class ScenarioPressureClockProtocol(Protocol):
    """Provide the server-owned aware cutoff for the run."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""
        ...


__all__ = [
    "PortfolioPressureProjectionProviderProtocol",
    "ScenarioPressureClockProtocol",
    "ScenarioPressurePreviewProtocol",
]
