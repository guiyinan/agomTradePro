"""Application orchestration for the fail-closed R2 market-structure slice."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from apps.data_center.domain.market_structure import (
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureObservation,
    MarketStructureResearchRequest,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
    PITMembershipSnapshot,
    SeriesPeriodCoverage,
    VersionedEvidenceReference,
    aggregate_market_structure,
    build_market_structure_evidence,
)
from apps.data_center.domain.pit import KnowledgeScope


class MarketStructureResearchGateway(Protocol):
    """Persistence and PIT read boundary for R2 Application orchestration."""

    def save_actor_definition(
        self,
        definition: InvestorActorDefinition,
    ) -> InvestorActorDefinition:
        """Persist one immutable investor taxonomy version."""

    def get_actor_definition(
        self,
        *,
        taxonomy_code: str,
        taxonomy_version: int,
        actor_code: str,
        as_of_time: datetime,
    ) -> InvestorActorDefinition | None:
        """Return one exact investor classification version."""

    def save_series_definition(
        self,
        definition: MarketStructureSeriesDefinition,
    ) -> MarketStructureSeriesDefinition:
        """Persist one immutable research-eligible series overlay."""

    def get_series_definition(
        self,
        reference: MarketStructureSeriesRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructureSeriesDefinition | None:
        """Return one exact research series definition version."""

    def list_series_observations(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> tuple[MarketStructureObservation, ...]:
        """Return verified asset-level PIT observations for one series."""

    def resolve_asset_group_membership(
        self,
        *,
        group_code: str,
        group_revision: int,
        effective_at: datetime,
        knowledge_at: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> PITMembershipSnapshot:
        """Resolve members using separate event and knowledge clocks."""

    def add_evidence(
        self,
        evidence: ImmutableMarketStructureEvidence,
    ) -> ImmutableMarketStructureEvidence:
        """Append one versioned, immutable research evidence record."""

    def get_evidence(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact immutable research evidence version."""


class MarketStructureGovernanceFacade:
    """Application entry point for actor and research-series governance."""

    def __init__(self, gateway: MarketStructureResearchGateway) -> None:
        self._gateway = gateway

    def register_actor(
        self,
        definition: InvestorActorDefinition,
    ) -> InvestorActorDefinition:
        """Register a caller-supplied investor taxonomy entry without seed data."""

        return self._gateway.save_actor_definition(definition)

    def register_series(
        self,
        definition: MarketStructureSeriesDefinition,
    ) -> MarketStructureSeriesDefinition:
        """Register a series only after canonical semantics can be verified."""

        return self._gateway.save_series_definition(definition)


class RunMarketStructureResearch:
    """Resolve PIT inputs, aggregate descriptively and persist sealed evidence."""

    def __init__(self, gateway: MarketStructureResearchGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        request: MarketStructureResearchRequest,
    ) -> ImmutableMarketStructureEvidence:
        """Run one fail-closed, research-only R2 aggregation."""

        definitions: list[MarketStructureSeriesDefinition] = []
        actor_definitions: list[InvestorActorDefinition] = []
        observations: list[MarketStructureObservation] = []
        included_observations: list[MarketStructureObservation] = []
        source_evidence: list[VersionedEvidenceReference] = []
        blockers: set[str] = set()

        for reference in request.series:
            definition = self._gateway.get_series_definition(
                reference,
                as_of_time=request.as_of_time,
            )
            if definition is None:
                blockers.add(
                    f"series_definition_missing:{reference.series_code}:v{reference.series_version}"
                )
                continue
            if (
                not definition.is_active
                or definition.effective_at > request.as_of_time
                or (
                    definition.effective_to is not None
                    and definition.effective_to <= request.as_of_time
                )
                or definition.available_at > request.as_of_time
                or (
                    definition.expires_at is not None
                    and definition.expires_at <= request.as_of_time
                )
            ):
                blockers.add(f"series_definition_unavailable:{definition.series_code}")
                continue
            definitions.append(definition)
            actor = self._gateway.get_actor_definition(
                taxonomy_code=definition.taxonomy_code,
                taxonomy_version=definition.taxonomy_version,
                actor_code=definition.actor_code,
                as_of_time=request.as_of_time,
            )
            if actor is None:
                blockers.add(f"actor_definition_missing:{definition.actor_code}")
            elif (
                not actor.is_active
                or actor.effective_at > request.as_of_time
                or (actor.effective_to is not None and actor.effective_to <= request.as_of_time)
                or actor.available_at > request.as_of_time
                or (actor.expires_at is not None and actor.expires_at <= request.as_of_time)
            ):
                blockers.add(f"actor_definition_unavailable:{definition.actor_code}")
            else:
                actor_definitions.append(actor)
            try:
                series_observations = self._gateway.list_series_observations(
                    definition,
                    as_of_time=request.as_of_time,
                    knowledge_scope=request.knowledge_scope,
                )
            except ValueError:
                blockers.add(f"series_evidence_invalid:{definition.series_code}")
                continue
            observations.extend(series_observations)
            source_evidence.extend(item.evidence for item in series_observations)

        membership_cache: dict[datetime, PITMembershipSnapshot] = {}
        for effective_at in sorted({item.effective_at for item in observations}):
            try:
                membership = self._gateway.resolve_asset_group_membership(
                    group_code=request.group_code,
                    group_revision=request.group_revision,
                    effective_at=effective_at,
                    knowledge_at=request.as_of_time,
                    knowledge_scope=request.knowledge_scope,
                )
            except ValueError:
                blockers.add(
                    "pit_membership_invalid:" f"{effective_at.astimezone(UTC).isoformat()}"
                )
                continue
            membership_cache[effective_at] = membership
            source_evidence.extend(membership.evidence)
            if not membership.asset_codes:
                blockers.add(
                    "pit_membership_missing:" f"{effective_at.astimezone(UTC).isoformat()}"
                )

        coverage: list[SeriesPeriodCoverage] = []
        for definition in definitions:
            for effective_at in sorted(membership_cache):
                membership = membership_cache[effective_at]
                expected = tuple(sorted(membership.asset_codes))
                observed = tuple(
                    sorted(
                        {
                            item.asset_code
                            for item in observations
                            if item.series_code == definition.series_code
                            and item.series_version == definition.series_version
                            and item.effective_at == effective_at
                            and item.asset_code in set(expected)
                        }
                    )
                )
                missing = tuple(sorted(set(expected) - set(observed)))
                coverage.append(
                    SeriesPeriodCoverage(
                        series_code=definition.series_code,
                        series_version=definition.series_version,
                        effective_at=effective_at,
                        expected_asset_codes=expected,
                        observed_asset_codes=observed,
                        missing_asset_codes=missing,
                    )
                )
        for observation in observations:
            selected_membership = membership_cache.get(observation.effective_at)
            if selected_membership is not None and observation.asset_code in set(
                selected_membership.asset_codes
            ):
                included_observations.append(observation)

        snapshot = aggregate_market_structure(
            request=request,
            definitions=tuple(definitions),
            observations=tuple(included_observations),
            external_blockers=tuple(sorted(blockers)),
            coverage=tuple(coverage),
        )
        evidence = build_market_structure_evidence(
            request=request,
            snapshot=snapshot,
            actor_definitions=tuple(actor_definitions),
            series_definitions=tuple(definitions),
            source_evidence=tuple(source_evidence),
        )
        return self._gateway.add_evidence(evidence)


class ReadMarketStructureEvidence:
    """Read one exact version without exposing mutable ORM state."""

    def __init__(self, gateway: MarketStructureResearchGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact immutable market-structure evidence version."""

        return self._gateway.get_evidence(
            evidence_key=evidence_key,
            evidence_version=evidence_version,
        )


__all__ = [
    "MarketStructureGovernanceFacade",
    "MarketStructureResearchGateway",
    "ReadMarketStructureEvidence",
    "RunMarketStructureResearch",
]
