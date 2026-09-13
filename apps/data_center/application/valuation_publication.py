"""Application writer for canonical valuation fact publications."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationState,
)
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import publication_selected_source_summary

from .control_plane import CanonicalPublicationRepositoryPort, PublishCanonicalDatasetUseCase
from .publication_idempotence import publication_replay_matches
from .publication_utils import publication_hash as _publication_hash
from .publication_utils import publication_member_from_reference


class ValuationPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted valuation facts to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[ValuationFact]
    ) -> list[PublicationFactReference]: ...


class PublishValuationBatchUseCase:
    """Publish one valuation snapshot with an explicit market-date boundary."""

    dataset_key = "equity.valuation.fact"
    fact_table = "data_center_valuation_fact"

    def __init__(
        self,
        *,
        fact_repository: ValuationPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[ValuationFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish valuation facts by ``val_date``.

        The publication boundary is the provider's persisted ``observed_at``;
        ``val_date`` only groups the daily valuation record and ``fetched_at``
        remains the local ingestion time.
        """

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_valuation_facts(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            raise ValueError("No publication candidates for equity.valuation.fact")
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
            raise ValueError("valuation observation cannot be later than publication time")

        validate_publication_evidence(policy, references, published_at=publish_time)
        publication_digest = _publication_hash(
            references, policy_identity=policy.identity if policy.uses_versioned_evidence else None
        )
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and publication_replay_matches(
            policy,
            current,
            references,
            self._publications.list_members(current.publication_id),
            knowledge_cutoff=publish_time,
        ):
            return current

        publication_id = str(
            uuid5(
                NAMESPACE_URL,
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_digest}",
            )
        )
        members = tuple(
            publication_member_from_reference(
                reference,
                member_id=str(uuid5(uuid5(NAMESPACE_URL, publication_id), reference.natural_key)),
                publication_id=publication_id,
                dataset_key=self.dataset_key,
            )
            for reference in references
        )
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=policy.identity,
            state=PublicationState.PUBLISHED,
            selected_source=(
                publication_selected_source_summary(references)
                if policy.uses_versioned_evidence
                else provider
            ),
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
            created_by="sync.valuation_fact",
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
                raise ValueError("Valuation publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Valuation natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


def _unique_valuation_facts(facts: Sequence[ValuationFact]) -> list[ValuationFact]:
    """Deduplicate valuation facts by their canonical natural key."""

    unique: dict[tuple[str, object, str], ValuationFact] = {}
    for fact in facts:
        unique.setdefault((fact.asset_code, fact.val_date, fact.source), fact)
    return list(unique.values())


__all__ = ["PublishValuationBatchUseCase", "ValuationPublicationCandidateRepositoryProtocol"]
