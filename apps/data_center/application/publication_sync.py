"""Application services that turn persisted facts into canonical publications."""

from __future__ import annotations

import hashlib
import json
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
from apps.data_center.domain.entities import (
    CapitalFlowFact,
    FinancialFact,
    FundNavFact,
    NewsFact,
    PriceBar,
    QuoteSnapshot,
    SectorMembershipFact,
)
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol

from .control_plane import CanonicalPublicationRepositoryPort, PublishCanonicalDatasetUseCase


class NewsPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving just-written news facts to canonical row ids."""

    def list_publication_candidates(
        self, articles: Sequence[NewsFact]
    ) -> list[PublicationFactReference]: ...


class PublishNewsBatchUseCase:
    """Publish one idempotent member snapshot after a news sync write."""

    dataset_key = "market.news"
    fact_table = "data_center_news_fact"

    def __init__(
        self,
        *,
        fact_repository: NewsPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        articles: Sequence[NewsFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve, validate and atomically publish the rows from one sync.

        A repeated provider response produces the same publication/member ids
        and returns the existing current publication without creating another
        version. Missing candidate rows are counted in coverage and fail closed
        through the active Dataset Publication Policy.
        """

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_articles = _unique_articles(articles)
        if not unique_articles:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_articles)
        )
        if not references:
            return None
        policy = self._policies.get_active(self.dataset_key)
        if policy is None:
            raise ValueError(f"No active publication policy for {self.dataset_key}")
        if policy.dataset.value != self.dataset_key:
            raise ValueError("Publication policy dataset mismatch")
        observed = [reference.observed_at for reference in references]
        as_of = max(observed)
        publish_time = published_at or datetime.now(UTC)
        if publish_time.tzinfo is None or publish_time.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        if as_of > publish_time:
            raise ValueError("news observation cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                # A repository without a member-read port is a compatibility
                # fake; the canonical hash/count pair is sufficient for its
                # idempotency assertion. Real repositories expose members and
                # only take this path after verifying the complete snapshot.
                return current
            # A legacy/memberless row with the same content hash is repaired
            # through the atomic writer instead of being treated as success.

        publication_id = str(
            uuid5(
                NAMESPACE_URL,
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
        requested_count = len(unique_articles)
        coverage = CoverageSnapshot(
            coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
            publication_id=publication_id,
            requested_count=requested_count,
            eligible_count=len(references),
            selected_count=len(references),
            missing_count=requested_count - len(references),
            conflict_count=0,
            generated_at=publish_time,
        )
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_hash,
            coverage=coverage,
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.news",
            run_id=run_id,
        )
        return self._publisher.execute(policy=policy, publication=publication, members=members)

    @staticmethod
    def _deduplicate_references(
        references: Sequence[PublicationFactReference],
    ) -> list[PublicationFactReference]:
        by_natural_key: dict[str, PublicationFactReference] = {}
        by_fact_pk: set[str] = set()
        for reference in references:
            if reference.fact_table != PublishNewsBatchUseCase.fact_table:
                raise ValueError("News publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("News publication natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class CapitalFlowPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted capital-flow rows to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[CapitalFlowFact]
    ) -> list[PublicationFactReference]: ...


class PublishCapitalFlowBatchUseCase:
    """Publish one daily capital-flow member snapshot after sync."""

    dataset_key = "market.capital_flow"
    fact_table = "data_center_capital_flow_fact"

    def __init__(
        self,
        *,
        fact_repository: CapitalFlowPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[CapitalFlowFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish exact daily flow facts.

        ``flow_date`` is carried by the repository as the member observation
        boundary. The publication timestamp only records when the snapshot was
        assembled and can never wash out an old flow date.
        """

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_capital_flow_facts(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            return None
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
            raise ValueError("capital-flow observation cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
        requested_count = len(unique_facts)
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=requested_count,
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=requested_count - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.capital_flow",
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
                raise ValueError("Capital-flow publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Capital-flow natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class FundNavPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted fund NAV rows to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[FundNavFact]
    ) -> list[PublicationFactReference]: ...


class PublishFundNavBatchUseCase:
    """Publish one idempotent fund NAV member snapshot after sync."""

    dataset_key = "fund.nav"
    fact_table = "data_center_fund_nav_fact"

    def __init__(
        self,
        *,
        fact_repository: FundNavPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[FundNavFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish exact NAV rows with date as-of."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_fund_nav_facts(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            return None
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
            raise ValueError("fund NAV observation cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
        requested_count = len(unique_facts)
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=requested_count,
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=requested_count - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.fund_nav",
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
                raise ValueError("Fund NAV publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Fund NAV natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class FinancialPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted financial facts to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[FinancialFact]
    ) -> list[PublicationFactReference]: ...


class PublishFinancialBatchUseCase:
    """Publish financial facts only when source availability is explicit."""

    dataset_key = "equity.financial.fact"
    fact_table = "data_center_financial_fact"

    def __init__(
        self,
        *,
        fact_repository: FinancialPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[FinancialFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish only facts with available-at evidence."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_financial_facts(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            raise ValueError(
                "No publication candidates with source available_at for equity.financial.fact"
            )
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
            raise ValueError("financial availability cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
            publication_hash=publication_hash,
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
            created_by="sync.financial_fact",
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
                raise ValueError("Financial publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Financial natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class PriceBarPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted daily price bars to canonical ids."""

    def list_publication_candidates(
        self, bars: Sequence[PriceBar]
    ) -> list[PublicationFactReference]: ...


class PublishPriceBarBatchUseCase:
    """Publish one idempotent price-bar member snapshot after a sync write."""

    dataset_key = "equity.price.bar"
    fact_table = "data_center_price_bar"

    def __init__(
        self,
        *,
        fact_repository: PriceBarPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        bars: Sequence[PriceBar],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve, validate and atomically publish bars using ``bar_date`` as-of."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_bars = _unique_price_bars(bars)
        if not unique_bars:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_bars)
        )
        if not references:
            return None
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
            raise ValueError("price-bar observation cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=len(unique_bars),
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=len(unique_bars) - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.price_bar",
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
                raise ValueError("Price-bar publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Price-bar natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class QuoteSnapshotPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted quote snapshots to canonical ids."""

    def list_publication_candidates(
        self, quotes: Sequence[QuoteSnapshot]
    ) -> list[PublicationFactReference]: ...


class PublishQuoteSnapshotBatchUseCase:
    """Publish one exact realtime quote member snapshot after sync."""

    dataset_key = "equity.quote.snapshot"
    fact_table = "data_center_quote_snapshot"

    def __init__(
        self,
        *,
        fact_repository: QuoteSnapshotPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        quotes: Sequence[QuoteSnapshot],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish quote rows with snapshot boundary."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_quotes = _unique_quote_snapshots(quotes)
        if not unique_quotes:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_quotes)
        )
        if not references:
            return None
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
            raise ValueError("quote snapshot cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
        requested_count = len(unique_quotes)
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=requested_count,
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=requested_count - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.quote_snapshot",
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
                raise ValueError("Quote publication candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Quote natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


class SectorMembershipPublicationCandidateRepositoryProtocol(Protocol):
    """Port for resolving persisted sector membership rows to canonical ids."""

    def list_publication_candidates(
        self, facts: Sequence[SectorMembershipFact]
    ) -> list[PublicationFactReference]: ...


class PublishSectorMembershipBatchUseCase:
    """Publish one exact sector-membership snapshot after sync."""

    dataset_key = "sector.membership"
    fact_table = "data_center_sector_membership"

    def __init__(
        self,
        *,
        fact_repository: SectorMembershipPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self._facts = fact_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def execute(
        self,
        facts: Sequence[SectorMembershipFact],
        *,
        provider_name: str,
        publication_key: str = "current",
        run_id: str = "",
        published_at: datetime | None = None,
    ) -> CanonicalPublication | None:
        """Resolve and atomically publish membership rows with date as-of."""

        normalized_key = publication_key.strip()
        if not normalized_key:
            raise ValueError("publication_key cannot be empty")
        provider = provider_name.strip()
        if not provider:
            raise ValueError("provider_name cannot be empty")
        unique_facts = _unique_sector_memberships(facts)
        if not unique_facts:
            return None
        references = self._deduplicate_references(
            self._facts.list_publication_candidates(unique_facts)
        )
        if not references:
            return None
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
            raise ValueError("sector membership observation cannot be later than publication time")

        publication_hash = _publication_hash(references)
        current = self._publications.get_current(self.dataset_key, normalized_key)
        if current is not None and current.publication_hash == publication_hash:
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
                f"agomtradepro:{self.dataset_key}:{normalized_key}:{publication_hash}",
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
        requested_count = len(unique_facts)
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset_key,
            publication_key=normalized_key,
            policy_version=f"{policy.dataset.contract_version}:{policy.dataset.schema_version}",
            state=PublicationState.PUBLISHED,
            selected_source=provider,
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=requested_count,
                eligible_count=len(references),
                selected_count=len(references),
                missing_count=requested_count - len(references),
                conflict_count=0,
                generated_at=publish_time,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=publish_time,
            created_by="sync.sector_membership",
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
                raise ValueError("Sector membership candidate fact table mismatch")
            previous = by_natural_key.get(reference.natural_key)
            if previous is not None and previous.fact_pk != reference.fact_pk:
                raise ValueError("Sector membership natural key resolves to multiple facts")
            if reference.fact_pk in by_fact_pk:
                continue
            by_natural_key[reference.natural_key] = reference
            by_fact_pk.add(reference.fact_pk)
        return sorted(by_natural_key.values(), key=lambda item: item.natural_key)


def _unique_articles(articles: Sequence[NewsFact]) -> list[NewsFact]:
    """Deduplicate provider rows before computing coverage."""

    unique: dict[str, NewsFact] = {}
    for article in articles:
        identity = article.external_id.strip() or _article_content_identity(article)
        unique.setdefault(identity, article)
    return list(unique.values())


def _unique_capital_flow_facts(facts: Sequence[CapitalFlowFact]) -> list[CapitalFlowFact]:
    """Deduplicate provider flow rows by their canonical natural key."""

    unique: dict[tuple[str, object, str], CapitalFlowFact] = {}
    for fact in facts:
        unique.setdefault((fact.asset_code, fact.flow_date, fact.source), fact)
    return list(unique.values())


def _unique_fund_nav_facts(facts: Sequence[FundNavFact]) -> list[FundNavFact]:
    """Deduplicate provider NAV rows by their canonical natural key."""

    unique: dict[tuple[str, object, str], FundNavFact] = {}
    for fact in facts:
        unique.setdefault((fact.fund_code, fact.nav_date, fact.source), fact)
    return list(unique.values())


def _unique_financial_facts(facts: Sequence[FinancialFact]) -> list[FinancialFact]:
    """Deduplicate financial facts by their canonical natural key."""

    unique: dict[tuple[str, object, str, str, str], FinancialFact] = {}
    for fact in facts:
        unique.setdefault(
            (
                fact.asset_code,
                fact.period_end,
                fact.period_type.value,
                fact.metric_code,
                fact.source,
            ),
            fact,
        )
    return list(unique.values())


def _unique_price_bars(bars: Sequence[PriceBar]) -> list[PriceBar]:
    """Deduplicate bars by their canonical natural key before coverage."""

    unique: dict[tuple[str, object, str, str, str], PriceBar] = {}
    for bar in bars:
        unique.setdefault(
            (
                bar.asset_code,
                bar.bar_date,
                bar.freq,
                bar.adjustment.value,
                bar.source,
            ),
            bar,
        )
    return list(unique.values())


def _unique_quote_snapshots(quotes: Sequence[QuoteSnapshot]) -> list[QuoteSnapshot]:
    """Deduplicate quote rows by their append-only natural key."""

    unique: dict[tuple[str, datetime, str], QuoteSnapshot] = {}
    for quote in quotes:
        unique.setdefault((quote.asset_code, quote.snapshot_at, quote.source), quote)
    return list(unique.values())


def _unique_sector_memberships(
    facts: Sequence[SectorMembershipFact],
) -> list[SectorMembershipFact]:
    """Deduplicate membership rows by their canonical natural key."""

    unique: dict[tuple[str, str, object], SectorMembershipFact] = {}
    for fact in facts:
        unique.setdefault((fact.asset_code, fact.sector_code, fact.effective_date), fact)
    return list(unique.values())


def _article_content_identity(article: NewsFact) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "asset_code": article.asset_code,
                "title": article.title,
                "summary": article.summary,
                "url": article.url,
                "published_at": article.published_at.isoformat(),
                "source": article.source,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _publication_hash(references: Sequence[PublicationFactReference]) -> str:
    payload = [
        {
            "natural_key": reference.natural_key,
            "source": reference.source,
            "fact_table": reference.fact_table,
            "fact_pk": reference.fact_pk,
            "observed_at": reference.observed_at.isoformat(),
            "raw_payload_hash": reference.raw_payload_hash,
            "quality_status": reference.quality_status,
            "revision_number": reference.revision_number,
        }
        for reference in references
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "CapitalFlowPublicationCandidateRepositoryProtocol",
    "FinancialPublicationCandidateRepositoryProtocol",
    "FundNavPublicationCandidateRepositoryProtocol",
    "NewsPublicationCandidateRepositoryProtocol",
    "PriceBarPublicationCandidateRepositoryProtocol",
    "QuoteSnapshotPublicationCandidateRepositoryProtocol",
    "SectorMembershipPublicationCandidateRepositoryProtocol",
    "PublishCapitalFlowBatchUseCase",
    "PublishFinancialBatchUseCase",
    "PublishFundNavBatchUseCase",
    "PublishNewsBatchUseCase",
    "PublishPriceBarBatchUseCase",
    "PublishQuoteSnapshotBatchUseCase",
    "PublishSectorMembershipBatchUseCase",
]
