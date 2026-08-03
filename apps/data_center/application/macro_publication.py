"""Application writer for canonical macro fact publications."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol

from .control_plane import CanonicalPublicationRepositoryPort, PublishCanonicalDatasetUseCase
from .publication_utils import publication_hash


class MacroPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted macro facts to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[MacroFact]
    ) -> list[PublicationFactReference]: ...


class PublishMacroBatchUseCase:
    """Publish macro facts only when source publication time is explicit."""

    dataset_key = "macro.fact"
    fact_table = "data_center_macro_fact"

    def __init__(
        self,
        *,
        fact_repository: MacroPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[MacroFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish macro facts by source publication date."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_macro_facts(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            raise ValueError("No publication candidates with source published_at for macro.fact")
        policy = self._policies.get_active(self.dataset_key)
        if policy is None:
            raise ValueError(f"No active publication policy for {self.dataset_key}")
        if policy.dataset.value != self.dataset_key:
            raise ValueError("Publication policy dataset mismatch")
        as_of = max(reference.observed_at for reference in references)
        publish_time = published_at or datetime.now(UTC)
        if publish_time.tzinfo is None or publish_time.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        if as_of > publish_time:
            raise ValueError("macro observation cannot be later than publication time")

        publication_digest = publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_digest:
            member_count_matches = current.member_count == len(references)
            member_reader = getattr(self._publications, "list_members", None)
            if member_count_matches and callable(member_reader):
                persisted_members = member_reader(current.publication_id)
                expected_keys = {reference.natural_key for reference in references}
                member_count_matches = (
                    len(persisted_members) == len(references)
                    and {member.natural_key for member in persisted_members} == expected_keys
                )
            if member_count_matches:
                return current

        publication_id = str(
            uuid5(
                NAMESPACE_URL,
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_digest}",
            )
        )
        members = tuple(
            PublicationMember(
                member_id=str(uuid5(uuid5(NAMESPACE_URL, publication_id), reference.natural_key)),
                publication_id=publication_id,
                dataset_key=self.dataset_key,
                natural_key=reference.natural_key,
                source=reference.source,
                source_record_id=reference.source_record_id,
                fact_table=reference.fact_table,
                fact_pk=reference.fact_pk,
                observed_at=reference.observed_at,
                raw_payload_hash=reference.raw_payload_hash,
                quality_status=reference.quality_status,
                revision_number=reference.revision_number,
            )
            for reference in references
        )
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_digest,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=len(unique_facts),
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=len(unique_facts) - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.macro_fact",
            run_id=run_id,
        )
        return self._publisher.execute(policy=policy, publication=publication, members=members)

    @classmethod
    def _deduplicate_references(
        cls,
        references: Sequence[PublicationFactReference],
    ) -> list[PublicationFactReference]:
        by_natural_key: dict[str, PublicationFactReference] = {}
        by_fact_pk: set[str] = set()
        for reference in references:
            if reference.fact_table != cls.fact_table:
                raise ValueError("Macro publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Macro natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


def _unique_macro_facts(facts: Sequence[MacroFact]) -> list[MacroFact]:
    """Deduplicate macro facts by their persisted natural key."""

    unique: dict[tuple[str, object, str, int], MacroFact] = {}
    for fact in facts:
        unique.setdefault(
            (fact.indicator_code, fact.reporting_period, fact.source, fact.revision_number),
            fact,
        )
    return list(unique.values())


__all__ = ["MacroPublicationCandidateRepositoryProtocol", "PublishMacroBatchUseCase"]
