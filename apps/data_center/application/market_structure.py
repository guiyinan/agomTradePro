"""Application orchestration for the fail-closed R2 market-structure slice."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from apps.data_center.domain.market_structure import (
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureObservation,
    MarketStructurePeriodCalendar,
    MarketStructurePeriodCalendarRef,
    MarketStructurePublicationAttestation,
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

    def save_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
    ) -> MarketStructurePeriodCalendar:
        """Persist one immutable caller-governed expected-period schedule."""

    def get_period_calendar(
        self,
        reference: MarketStructurePeriodCalendarRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePeriodCalendar | None:
        """Return one exact calendar version available at the request clock."""

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

    def get_evidence_at(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
        as_of_time: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact evidence version known by a PIT cutoff."""


class MarketStructurePublicationGate(Protocol):
    """Canonical Publication boundary for R2 governance artifacts."""

    def attest_actor(
        self,
        definition: InvestorActorDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact taxonomy member proof or fail closed."""

    def attest_series(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact series member proof or fail closed."""

    def attest_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact expected-period calendar proof or fail closed."""


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

    def register_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
    ) -> MarketStructurePeriodCalendar:
        """Register an exact expected-period schedule without business seed data."""

        return self._gateway.save_period_calendar(calendar)


class RunMarketStructureResearch:
    """Resolve PIT inputs, aggregate descriptively and persist sealed evidence."""

    def __init__(
        self,
        gateway: MarketStructureResearchGateway,
        publication_gate: MarketStructurePublicationGate,
    ) -> None:
        self._gateway = gateway
        self._publication_gate = publication_gate

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
        governance_publications: list[MarketStructurePublicationAttestation] = []
        blockers: set[str] = set()
        period_calendar = self._gateway.get_period_calendar(
            request.period_calendar,
            as_of_time=request.as_of_time,
        )
        if period_calendar is None:
            blockers.add(
                "period_calendar_missing:"
                f"{request.period_calendar.calendar_code}:"
                f"v{request.period_calendar.calendar_version}"
            )
        else:
            try:
                calendar_publication = self._publication_gate.attest_period_calendar(
                    period_calendar,
                    as_of_time=request.as_of_time,
                )
            except ValueError:
                calendar_publication = None
                blockers.add("period_calendar_publication_invalid")
            if calendar_publication is None:
                blockers.add(
                    "period_calendar_unpublished:"
                    f"{request.period_calendar.calendar_code}:"
                    f"v{request.period_calendar.calendar_version}"
                )
                period_calendar = None
            else:
                governance_publications.append(calendar_publication)
        expected_periods = period_calendar.periods if period_calendar is not None else ()

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
            try:
                series_publication = self._publication_gate.attest_series(
                    definition,
                    as_of_time=request.as_of_time,
                )
            except ValueError:
                blockers.add(f"series_publication_invalid:{definition.series_code}")
                continue
            if series_publication is None:
                blockers.add(f"series_definition_unpublished:{definition.series_code}")
                continue
            actor = self._gateway.get_actor_definition(
                taxonomy_code=definition.taxonomy_code,
                taxonomy_version=definition.taxonomy_version,
                actor_code=definition.actor_code,
                as_of_time=request.as_of_time,
            )
            if actor is None:
                blockers.add(f"actor_definition_missing:{definition.actor_code}")
                continue
            elif (
                not actor.is_active
                or actor.effective_at > request.as_of_time
                or (actor.effective_to is not None and actor.effective_to <= request.as_of_time)
                or actor.available_at > request.as_of_time
                or (actor.expires_at is not None and actor.expires_at <= request.as_of_time)
            ):
                blockers.add(f"actor_definition_unavailable:{definition.actor_code}")
                continue
            else:
                try:
                    actor_publication = self._publication_gate.attest_actor(
                        actor,
                        as_of_time=request.as_of_time,
                    )
                except ValueError:
                    blockers.add(f"actor_publication_invalid:{definition.actor_code}")
                    continue
                if actor_publication is None:
                    blockers.add(f"actor_definition_unpublished:{definition.actor_code}")
                    continue
                if (
                    actor_publication.publication_id != series_publication.publication_id
                    or actor_publication.publication_hash != series_publication.publication_hash
                ):
                    blockers.add(f"taxonomy_publication_snapshot_mismatch:{definition.series_code}")
                    continue
                definitions.append(definition)
                actor_definitions.append(actor)
                governance_publications.extend((actor_publication, series_publication))
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

        membership_cache: dict[datetime, PITMembershipSnapshot] = {}
        for effective_at in expected_periods:
            if effective_at > request.as_of_time:
                blockers.add(
                    "period_calendar_future_period:" f"{effective_at.astimezone(UTC).isoformat()}"
                )
                continue
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
        for reference in request.series:
            for effective_at in expected_periods:
                selected_membership = membership_cache.get(effective_at)
                expected = (
                    tuple(sorted(selected_membership.asset_codes))
                    if selected_membership is not None
                    else ()
                )
                expected_set = set(expected)
                observed = tuple(
                    sorted(
                        {
                            item.asset_code
                            for item in observations
                            if item.series_code == reference.series_code
                            and item.series_version == reference.series_version
                            and item.effective_at == effective_at
                            and item.asset_code in expected_set
                        }
                    )
                )
                missing = tuple(sorted(expected_set - set(observed)))
                coverage.append(
                    SeriesPeriodCoverage(
                        series_code=reference.series_code,
                        series_version=reference.series_version,
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
                source_evidence.append(observation.evidence)

        snapshot = aggregate_market_structure(
            request=request,
            period_calendar=period_calendar,
            definitions=tuple(definitions),
            observations=tuple(included_observations),
            external_blockers=tuple(sorted(blockers)),
            coverage=tuple(coverage),
        )
        evidence = build_market_structure_evidence(
            request=request,
            snapshot=snapshot,
            period_calendar=period_calendar,
            actor_definitions=tuple(actor_definitions),
            series_definitions=tuple(definitions),
            source_evidence=tuple(source_evidence),
            governance_publications=tuple(
                {item.attestation_hash: item for item in governance_publications}.values()
            ),
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

    def execute_at(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
        as_of_time: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return one exact immutable version only if known at the cutoff."""

        return self._gateway.get_evidence_at(
            evidence_key=evidence_key,
            evidence_version=evidence_version,
            as_of_time=as_of_time,
        )


__all__ = [
    "MarketStructureGovernanceFacade",
    "MarketStructurePublicationGate",
    "MarketStructureResearchGateway",
    "ReadMarketStructureEvidence",
    "RunMarketStructureResearch",
]
