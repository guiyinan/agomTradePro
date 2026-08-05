"""Dependency-injected ports for Risk Center scenario use cases."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.risk_center.application.scenario_dtos import (
    ActivateScenarioSetCommandDTO,
    CreateScenarioRevisionCommandDTO,
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
)
from apps.risk_center.domain.scenarios import (
    ScenarioActivation,
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioRunEvidence,
    ScenarioSetRevision,
    ScenarioType,
)


class ScenarioQueryRepositoryProtocol(Protocol):
    """Read immutable scenario definitions, revisions, and active sets."""

    def list_definitions(self, *, include_retired: bool = False) -> tuple[ScenarioDefinition, ...]:
        """List definitions in repository-defined display order."""

    def list_current_revisions(
        self,
        *,
        scenario_type: ScenarioType | None = None,
        include_inactive: bool = False,
    ) -> tuple[ScenarioRevision, ...]:
        """Return the latest eligible revision per requested definition scope."""

    def get_revision(
        self,
        identifier: str,
        *,
        version: int | None = None,
    ) -> ScenarioRevision | None:
        """Resolve a revision id, scenario key, or legacy alias."""

    def list_revisions(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        """List every immutable revision for a key or legacy alias, newest first."""

    def get_active_set_revision(
        self,
        *,
        environment: str,
        purpose: str,
    ) -> ScenarioSetRevision | None:
        """Return the only active set revision in a runtime scope."""


class ScenarioRevisionRepositoryProtocol(Protocol):
    """Append-only persistence boundary for scenario revisions."""

    def save_revision(self, revision: ScenarioRevision) -> ScenarioRevision:
        """Append a validated revision without mutating prior versions."""

    def append_next_revision(
        self,
        command: CreateScenarioRevisionCommandDTO,
    ) -> ScenarioRevision:
        """Lock a definition and allocate the next version server-side."""


class ScenarioActivationRepositoryProtocol(Protocol):
    """Controlled persistence boundary for active-set pointers."""

    def activate(self, activation: ScenarioActivation) -> ScenarioActivation:
        """Atomically replace the active pointer in one scope."""

    def activate_set_revision(
        self,
        command: ActivateScenarioSetCommandDTO,
    ) -> ScenarioActivation:
        """Switch the active pointer with optimistic locking and a row lock."""


class ScenarioRunEvidenceRepositoryProtocol(Protocol):
    """Append-only persistence boundary for reproducibility evidence."""

    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        """Persist exact run inputs and the deterministic result digest."""


class PortfolioSnapshotProviderProtocol(Protocol):
    """Portfolio-owned immutable snapshot provider."""

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        as_of_time: datetime,
    ) -> PortfolioSnapshotDTO | None:
        """Return an exact snapshot version without querying holdings from Risk Center."""


class ScenarioMarketDataProviderProtocol(Protocol):
    """Data Center-owned published historical/current data provider."""

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        """Return data visible at the requested knowledge boundary."""


__all__ = [
    "PortfolioSnapshotProviderProtocol",
    "ScenarioActivationRepositoryProtocol",
    "ScenarioMarketDataProviderProtocol",
    "ScenarioQueryRepositoryProtocol",
    "ScenarioRevisionRepositoryProtocol",
    "ScenarioRunEvidenceRepositoryProtocol",
]
