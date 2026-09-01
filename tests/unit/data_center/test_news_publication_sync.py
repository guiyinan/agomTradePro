from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.data_center.application.dtos import SyncNewsRequest
from apps.data_center.application.publication_sync import PublishNewsBatchUseCase
from apps.data_center.application.sync_use_cases import SyncNewsUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import NewsFact, ProviderConfig

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(
        self, articles: Sequence[NewsFact]
    ) -> list[PublicationFactReference]:
        external_ids = {article.external_id for article in articles}
        return [
            reference for reference in self.references if reference.source_record_id in external_ids
        ]


class _PolicyRepository:
    def __init__(self, policy: PublicationPolicy | None) -> None:
        self.policy = policy

    def get_active(self, _dataset_key: str):
        return self.policy


class _ContractRepository:
    def __init__(self, freshness_seconds: int | None = 172_800) -> None:
        self.freshness_seconds = freshness_seconds

    def get_active(self, _dataset_key: str):
        if self.freshness_seconds is None:
            return None
        return SimpleNamespace(freshness_seconds=self.freshness_seconds)


class _PublicationRepository:
    def __init__(self) -> None:
        self.current: CanonicalPublication | None = None
        self.published: list[tuple[CanonicalPublication, tuple[object, ...]]] = []

    def get_current(self, _dataset_key: str, _publication_key: str):
        return self.current

    def publish_with_members(self, publication, members):
        self.current = publication
        self.published.append((publication, members))
        return publication


def _policy() -> PublicationPolicy:
    return PublicationPolicy(
        dataset=DatasetKey("market.news", "1.0", "1.0"),
        minimum_coverage_ratio=0.95,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=("source", "observed_at", "payload_hash"),
        retention_days=730,
    )


def _article(external_id: str, observed_at: datetime) -> NewsFact:
    return NewsFact(
        asset_code="",
        title=f"headline-{external_id}",
        published_at=observed_at,
        source="provider-main",
        external_id=external_id,
    )


def _reference(external_id: str, fact_pk: str, observed_at: datetime) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"provider-main:{external_id}",
        source="provider-main",
        source_record_id=external_id,
        fact_table="data_center_news_fact",
        fact_pk=fact_pk,
        observed_at=observed_at,
        raw_payload_hash=("a" * 64),
    )


def test_news_sync_publication_binds_members_and_as_of_boundary() -> None:
    articles = [_article("n1", datetime(2026, 8, 3, 10, tzinfo=UTC)), _article("n2", NOW)]
    repository = _PublicationRepository()
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository(
            [_reference("n1", "11", articles[0].published_at), _reference("n2", "12", NOW)]
        ),
        publication_repository=repository,
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(),
    )

    publication = use_case.execute(
        articles,
        provider_name="provider-main",
        published_at=NOW,
        run_id="run-1",
    )

    assert publication is not None
    assert publication.as_of == NOW
    assert publication.member_count == 2
    assert publication.coverage.selected_count == 2
    assert publication.coverage.missing_count == 0
    assert len(repository.published) == 1
    assert {member.fact_pk for member in repository.published[0][1]} == {"11", "12"}


def test_news_sync_publication_is_idempotent_for_same_member_snapshot() -> None:
    articles = [_article("n1", datetime(2026, 8, 3, 10, tzinfo=UTC))]
    repository = _PublicationRepository()
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository([_reference("n1", "11", articles[0].published_at)]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(),
    )

    first = use_case.execute(articles, provider_name="provider-main", published_at=NOW)
    second = use_case.execute(articles, provider_name="provider-main", published_at=NOW)

    assert first is second
    assert len(repository.published) == 1


def test_news_sync_repairs_memberless_same_hash_publication() -> None:
    articles = [_article("n1", datetime(2026, 8, 3, 10, tzinfo=UTC))]
    repository = _PublicationRepository()
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository([_reference("n1", "11", articles[0].published_at)]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(),
    )

    first = use_case.execute(articles, provider_name="provider-main", published_at=NOW)
    assert first is not None
    repository.current = SimpleNamespace(
        publication_id=first.publication_id,
        publication_hash=first.publication_hash,
        member_count=0,
    )

    repaired = use_case.execute(articles, provider_name="provider-main", published_at=NOW)

    assert repaired is not None
    assert repaired.member_count == 1
    assert len(repository.published) == 2


def test_news_sync_publication_fails_closed_below_coverage_policy() -> None:
    articles = [_article("n1", NOW), _article("n2", NOW)]
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository([_reference("n1", "11", NOW)]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(articles, provider_name="provider-main", published_at=NOW)


def test_current_news_publication_excludes_members_outside_freshness_window() -> None:
    stale_time = NOW - timedelta(seconds=172_801)
    articles = [_article("stale", stale_time), _article("fresh", NOW)]
    repository = _PublicationRepository()
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository(
            [
                _reference("stale", "10", stale_time),
                _reference("fresh", "11", NOW),
            ]
        ),
        publication_repository=repository,
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(),
    )

    publication = use_case.execute(
        articles,
        provider_name="provider-main",
        published_at=NOW,
    )

    assert publication is not None
    assert publication.member_count == 1
    assert publication.coverage.requested_count == 1
    assert [member.fact_pk for member in repository.published[0][1]] == ["11"]


def test_current_news_publication_fails_closed_without_freshness_contract() -> None:
    use_case = PublishNewsBatchUseCase(
        fact_repository=_CandidateRepository([_reference("n1", "11", NOW)]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(_policy()),
        contract_repository=_ContractRepository(freshness_seconds=None),
    )

    with pytest.raises(ValueError, match="freshness contract"):
        use_case.execute([_article("n1", NOW)], provider_name="provider-main", published_at=NOW)


def test_sync_news_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_news(self, _asset_code: str, limit: int = 20) -> list[NewsFact]:
            return [_article("n1", NOW)][:limit]

    class _ProviderRepository:
        def __init__(self) -> None:
            self.config = ProviderConfig(
                id=1,
                name="provider-main",
                source_type="tushare",
                is_active=True,
                priority=1,
                api_key="",
                api_secret="",
                http_url="",
                api_endpoint="",
                extra_config={},
                description="",
            )
            self.saved = []

        def get_by_id(self, _provider_id: int):
            return self.config

        def save(self, config):
            self.saved.append(config)
            self.config = config
            return config

    class _Registry:
        def __init__(self) -> None:
            self.provider = _Provider()

        def get_by_id(self, _provider_id: int):
            return self.provider

        def record_success(self, *_args) -> None:
            return None

        def record_failure(self, *_args) -> None:
            return None

    class _Facts:
        def __init__(self) -> None:
            self.saved: list[NewsFact] = []

        def bulk_insert(self, articles: list[NewsFact]) -> int:
            self.saved.extend(articles)
            return len(articles)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[NewsFact], str]] = []

        def execute(self, articles, *, provider_name: str):
            self.calls.append((list(articles), provider_name))
            return None

    provider_repo = _ProviderRepository()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncNewsUseCase(
        provider_repo=provider_repo,
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(SyncNewsRequest(provider_id=1, asset_code="", limit=10))

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]
