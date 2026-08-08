from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.dtos import SyncPriceRequest
from apps.data_center.application.publication_sync import PublishPriceBarBatchUseCase
from apps.data_center.application.sync_use_cases import SyncPriceUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import PriceBar, ProviderConfig
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.market_data_repositories import PriceBarRepository
from apps.data_center.infrastructure.models import PriceBarModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
BAR_DATE = date(2026, 8, 3)
OBSERVED_AT = datetime(2026, 8, 2, 16, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _bars):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("equity.price.bar", "1.0", "1.0"),
            minimum_coverage_ratio=0.99,
            allow_partial=True,
            conflict_action="quarantine",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=3650,
        )


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


def _bar(asset_code: str = "000001.SZ", bar_date: date = BAR_DATE) -> PriceBar:
    return PriceBar(
        asset_code=asset_code,
        bar_date=bar_date,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        source="provider-main",
        fetched_at=PUBLISHED_AT,
    )


def _reference(
    asset_code: str = "000001.SZ",
    fact_pk: str = "101",
) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:{BAR_DATE.isoformat()}:1d:none:provider-main",
        source="provider-main",
        source_record_id=f"bar-{asset_code}",
        fact_table="data_center_price_bar",
        fact_pk=fact_pk,
        observed_at=OBSERVED_AT,
        raw_payload_hash="a" * 64,
    )


def test_price_bar_publication_uses_bar_date_as_of_and_exact_members() -> None:
    repository = _PublicationRepository()
    use_case = PublishPriceBarBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    publication = use_case.execute(
        [_bar()], provider_name="provider-main", published_at=PUBLISHED_AT
    )

    assert publication is not None
    assert publication.as_of == OBSERVED_AT
    assert publication.as_of != _bar().fetched_at
    assert publication.coverage.selected_count == 1
    assert publication.coverage.missing_count == 0
    assert repository.published[0][1][0].fact_pk == "101"
    assert repository.published[0][1][0].observed_at == OBSERVED_AT


def test_price_bar_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishPriceBarBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute([_bar()], provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute([_bar()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_price_bar_publication_fails_closed_below_coverage_policy() -> None:
    bars = [_bar("000001.SZ"), _bar("600000.SH")]
    use_case = PublishPriceBarBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ")]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(bars, provider_name="provider-main", published_at=PUBLISHED_AT)


@pytest.mark.django_db
def test_price_bar_repository_candidate_preserves_bar_date_and_source_evidence() -> None:
    row = PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=BAR_DATE,
        freq="1d",
        adjustment="none",
        open=10,
        high=10.5,
        low=9.8,
        close=10.2,
        source="provider-main",
        source_record_id="bar-1",
        raw_payload_hash="b" * 64,
        fetched_at=PUBLISHED_AT,
    )

    references = PriceBarRepository().list_publication_candidates([_bar()])

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source == "provider-main"
    assert references[0].source_record_id == "bar-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == OBSERVED_AT
    assert references[0].observed_at != row.fetched_at


def test_sync_price_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_price_history(self, _asset_code, _start, _end) -> list[PriceBar]:
            return [_bar()]

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

        def get_by_id(self, _provider_id: int):
            return self.config

        def save(self, config):
            self.config = config
            return config

    class _Registry:
        def get_by_id(self, _provider_id: int):
            return _Provider()

        def record_success(self, *_args) -> None:
            return None

        def record_failure(self, *_args) -> None:
            return None

    class _Facts:
        def __init__(self) -> None:
            self.saved: list[PriceBar] = []

        def bulk_upsert(self, bars: list[PriceBar]) -> int:
            self.saved.extend(bars)
            return len(bars)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[PriceBar], str]] = []

        def execute(self, bars, *, provider_name: str):
            self.calls.append((list(bars), provider_name))
            return None

    provider_repo = _ProviderRepository()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncPriceUseCase(
        provider_repo=provider_repo,
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(
        SyncPriceRequest(
            provider_id=1,
            asset_code="000001.SZ",
            start=BAR_DATE,
            end=BAR_DATE,
        )
    )

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]
