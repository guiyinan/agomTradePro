"""Exact typed inputs retained with one reproducible Scenario preview."""

from __future__ import annotations

from dataclasses import dataclass

from apps.risk_center.application.scenario_dtos import (
    PortfolioSnapshotDTO,
    ScenarioMarketDataDTO,
    ScenarioRunRequestDTO,
)
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
from apps.risk_center.domain.scenarios import ScenarioImpact, ScenarioRevision


@dataclass(frozen=True)
class ScenarioImpactContext:
    """Bind a preview result to the exact revision, snapshot, and market read."""

    request: ScenarioRunRequestDTO
    revision: ScenarioRevision
    snapshot: PortfolioSnapshotDTO
    market_data: ScenarioMarketDataDTO
    impact: ScenarioImpact

    def __post_init__(self) -> None:
        """Reject context parts that cannot have come from one valid preview."""

        if self.request.scenario_revision_id != self.revision.revision_id:
            raise ValueError("ScenarioImpactContext revision does not match request")
        if self.request.portfolio_snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("ScenarioImpactContext snapshot does not match request")
        if self.snapshot.as_of_time > self.request.as_of_time:
            raise ValueError("ScenarioImpactContext snapshot is newer than request cutoff")
        if self.market_data.must_not_use_for_decision:
            raise ValueError("ScenarioImpactContext cannot retain blocked market data")
        if not self.market_data.evidence_ids:
            raise ValueError("ScenarioImpactContext market evidence ids are required")
        if self.market_data.published_at > self.request.as_of_time:
            raise ValueError("ScenarioImpactContext market publication is newer than cutoff")
        if self.market_data.observation_precision is SourceObservationPrecision.TIMESTAMP:
            if self.market_data.observed_at is None:
                raise ValueError("ScenarioImpactContext timestamp observation is missing")
            if self.market_data.observed_at > self.request.as_of_time:
                raise ValueError("ScenarioImpactContext market observation is newer than cutoff")
        elif self.market_data.observation_precision is SourceObservationPrecision.DATE:
            if self.market_data.observed_on is None:
                raise ValueError("ScenarioImpactContext date observation is missing")
            if self.market_data.observed_on >= self.request.as_of_time.date():
                raise ValueError("ScenarioImpactContext date observation is not before cutoff")
        else:
            raise ValueError("ScenarioImpactContext market observation precision is unknown")
        if self.impact.scenario_revision_id != self.revision.revision_id:
            raise ValueError("ScenarioImpactContext impact does not match revision")


__all__ = ["ScenarioImpactContext"]
