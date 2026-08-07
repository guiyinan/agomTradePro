"""Canonical Publication gate for Data Center-owned R2 governance artifacts."""

from __future__ import annotations

from datetime import datetime

from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.domain.control_plane import (
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.market_structure import (
    MARKET_STRUCTURE_CALENDAR_DATASET,
    MARKET_STRUCTURE_TAXONOMY_DATASET,
    InvestorActorDefinition,
    MarketStructureGovernanceArtifactKind,
    MarketStructurePeriodCalendar,
    MarketStructurePublicationAttestation,
    MarketStructureSeriesDefinition,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.market_structure_models import (
    InvestorActorDefinitionModel,
    MarketStructurePeriodCalendarModel,
    MarketStructureSeriesDefinitionModel,
)


def market_structure_taxonomy_publication_key(
    taxonomy_code: str,
    taxonomy_version: int,
) -> str:
    """Return the canonical Publication scope for one taxonomy version."""

    return f"taxonomy:{taxonomy_code}:v{taxonomy_version}"


def market_structure_calendar_publication_key(
    calendar_code: str,
    calendar_version: int,
) -> str:
    """Return the canonical Publication scope for one calendar version."""

    return f"calendar:{calendar_code}:v{calendar_version}"


def market_structure_actor_member_key(definition: InvestorActorDefinition) -> str:
    """Return the immutable natural key for one taxonomy actor member."""

    return (
        f"actor:{definition.taxonomy_code}:v{definition.taxonomy_version}:"
        f"{definition.actor_code}"
    )


def market_structure_series_member_key(
    definition: MarketStructureSeriesDefinition,
) -> str:
    """Return the immutable natural key for one series member."""

    return f"series:{definition.series_code}:v{definition.series_version}"


def market_structure_calendar_member_key(
    calendar: MarketStructurePeriodCalendar,
) -> str:
    """Return the immutable natural key for one period-calendar member."""

    return f"calendar:{calendar.calendar_code}:v{calendar.calendar_version}"


class DjangoMarketStructurePublicationGate:
    """Attest exact governance rows against a PIT canonical Publication."""

    def __init__(
        self,
        repository: CanonicalPublicationRepository | None = None,
    ) -> None:
        self._repository = repository or CanonicalPublicationRepository()

    def attest_actor(
        self,
        definition: InvestorActorDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact taxonomy publication proof for one actor row."""

        models = tuple(
            InvestorActorDefinitionModel._default_manager.filter(
                taxonomy_code=definition.taxonomy_code,
                taxonomy_version=definition.taxonomy_version,
                actor_code=definition.actor_code,
            ).order_by("pk")
        )
        if len(models) != 1 or models[0].to_domain() != definition:
            raise ValueError("market-structure actor publication owner row was substituted")
        return self._attest(
            artifact_kind=MarketStructureGovernanceArtifactKind.ACTOR,
            dataset_key=MARKET_STRUCTURE_TAXONOMY_DATASET,
            publication_key=market_structure_taxonomy_publication_key(
                definition.taxonomy_code,
                definition.taxonomy_version,
            ),
            natural_key=market_structure_actor_member_key(definition),
            fact_table=InvestorActorDefinitionModel._meta.db_table,
            fact_pk=str(models[0].pk),
            artifact_hash=definition.definition_hash,
            artifact_source=definition.source,
            artifact_available_at=definition.available_at,
            as_of_time=as_of_time,
        )

    def attest_series(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact taxonomy publication proof for one series row."""

        models = tuple(
            MarketStructureSeriesDefinitionModel._default_manager.filter(
                series_code=definition.series_code,
                series_version=definition.series_version,
            ).order_by("pk")
        )
        if len(models) != 1 or models[0].to_domain() != definition:
            raise ValueError("market-structure series publication owner row was substituted")
        return self._attest(
            artifact_kind=MarketStructureGovernanceArtifactKind.SERIES,
            dataset_key=MARKET_STRUCTURE_TAXONOMY_DATASET,
            publication_key=market_structure_taxonomy_publication_key(
                definition.taxonomy_code,
                definition.taxonomy_version,
            ),
            natural_key=market_structure_series_member_key(definition),
            fact_table=MarketStructureSeriesDefinitionModel._meta.db_table,
            fact_pk=str(models[0].pk),
            artifact_hash=definition.definition_hash,
            artifact_source=definition.source,
            artifact_available_at=definition.available_at,
            as_of_time=as_of_time,
        )

    def attest_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        """Return exact calendar publication proof for one schedule row."""

        models = tuple(
            MarketStructurePeriodCalendarModel._default_manager.filter(
                calendar_code=calendar.calendar_code,
                calendar_version=calendar.calendar_version,
            ).order_by("pk")
        )
        if len(models) != 1 or models[0].to_domain() != calendar:
            raise ValueError("market-structure calendar publication owner row was substituted")
        return self._attest(
            artifact_kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
            dataset_key=MARKET_STRUCTURE_CALENDAR_DATASET,
            publication_key=market_structure_calendar_publication_key(
                calendar.calendar_code,
                calendar.calendar_version,
            ),
            natural_key=market_structure_calendar_member_key(calendar),
            fact_table=MarketStructurePeriodCalendarModel._meta.db_table,
            fact_pk=str(models[0].pk),
            artifact_hash=calendar.calendar_hash,
            artifact_source=calendar.source,
            artifact_available_at=calendar.available_at,
            as_of_time=as_of_time,
        )

    def verify_attestation(
        self,
        attestation: MarketStructurePublicationAttestation,
        *,
        as_of_time: datetime,
    ) -> bool:
        """Reread the exact owner row and Publication/member graph."""

        try:
            primary_key = int(attestation.fact_pk)
        except ValueError as error:
            raise ValueError("market-structure publication fact_pk is invalid") from error
        if attestation.artifact_kind is MarketStructureGovernanceArtifactKind.ACTOR:
            model = InvestorActorDefinitionModel._default_manager.filter(pk=primary_key).first()
            if model is None:
                return False
            actual = self.attest_actor(model.to_domain(), as_of_time=as_of_time)
        elif attestation.artifact_kind is MarketStructureGovernanceArtifactKind.SERIES:
            series_model = MarketStructureSeriesDefinitionModel._default_manager.filter(
                pk=primary_key
            ).first()
            if series_model is None:
                return False
            actual = self.attest_series(series_model.to_domain(), as_of_time=as_of_time)
        else:
            calendar_model = MarketStructurePeriodCalendarModel._default_manager.filter(
                pk=primary_key
            ).first()
            if calendar_model is None:
                return False
            actual = self.attest_period_calendar(
                calendar_model.to_domain(),
                as_of_time=as_of_time,
            )
        return actual == attestation

    def _attest(
        self,
        *,
        artifact_kind: MarketStructureGovernanceArtifactKind,
        dataset_key: str,
        publication_key: str,
        natural_key: str,
        fact_table: str,
        fact_pk: str,
        artifact_hash: str,
        artifact_source: str,
        artifact_available_at: datetime,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        publication = self._repository.get_as_of(
            dataset_key,
            publication_key,
            as_of_time,
        )
        if publication is None:
            return None
        if (
            publication.state not in {PublicationState.PUBLISHED, PublicationState.SUPERSEDED}
            or publication.must_not_use_for_decision
            or publication.as_of is None
            or publication.published_at is None
            or publication.published_at > as_of_time
            or publication.as_of > as_of_time
        ):
            raise ValueError("market-structure governance publication is unavailable")
        members = tuple(self._repository.list_members(publication.publication_id))
        if (
            len(members) != publication.member_count
            or publication.coverage.selected_count != publication.member_count
            or publication.coverage.conflict_count != publication.conflict_count
        ):
            raise ValueError("market-structure governance publication coverage was tampered")
        references = tuple(self._reference(member) for member in members)
        if publication_hash(references) != publication.publication_hash:
            raise ValueError("market-structure governance publication hash mismatch")
        matches = tuple(member for member in members if member.natural_key == natural_key)
        if len(matches) != 1:
            return None
        member = matches[0]
        if (
            member.dataset_key != dataset_key
            or member.fact_table != fact_table
            or member.fact_pk != fact_pk
            or member.source != artifact_source
            or member.source_record_id != artifact_hash
            or member.raw_payload_hash != artifact_hash
            or member.quality_status != "accepted"
            or member.revision_number != 1
            or member.observed_at != artifact_available_at
        ):
            raise ValueError("market-structure governance publication member was substituted")
        return MarketStructurePublicationAttestation.create(
            artifact_kind=artifact_kind,
            dataset_key=dataset_key,
            publication_key=publication_key,
            publication_id=publication.publication_id,
            publication_hash=publication.publication_hash,
            publication_as_of=publication.as_of,
            published_at=publication.published_at,
            member_id=member.member_id,
            member_natural_key=member.natural_key,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            artifact_hash=artifact_hash,
            member_observed_at=artifact_available_at,
        )

    @staticmethod
    def _reference(member: PublicationMember) -> PublicationFactReference:
        if member.observed_at is None:
            raise ValueError("market-structure governance member lacks observed_at")
        return PublicationFactReference(
            natural_key=member.natural_key,
            source=member.source,
            source_record_id=member.source_record_id,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            observed_at=member.observed_at,
            raw_payload_hash=member.raw_payload_hash,
            quality_status=member.quality_status,
            revision_number=member.revision_number,
        )


__all__ = [
    "DjangoMarketStructurePublicationGate",
    "market_structure_actor_member_key",
    "market_structure_calendar_member_key",
    "market_structure_calendar_publication_key",
    "market_structure_series_member_key",
    "market_structure_taxonomy_publication_key",
]
