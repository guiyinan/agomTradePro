from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.current_valuation_sync import SyncCurrentValuationBatchUseCase
from apps.data_center.application.dtos import SyncValuationRequest
from apps.data_center.application.publication_sync import PublishValuationBatchUseCase
from apps.data_center.application.sync_use_cases import SyncValuationUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import ProviderConfig, ValuationFact
from apps.data_center.infrastructure.fundamental_fact_repositories import ValuationFactRepository
from apps.data_center.infrastructure.models import ValuationFactModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
VAL_DATE = date(2026, 8, 3)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
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


def _fact(asset_code: str = "000001.SZ") -> ValuationFact:
    return ValuationFact(
        asset_code=asset_code,
        val_date=VAL_DATE,
        pe_ttm=12.3,
        pb=1.7,
        source="provider-main",
        available_at=None,
        fetched_at=PUBLISHED_AT,
    )


def _reference(
    asset_code: str = "000001.SZ",
    fact_pk: str = "201",
) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:{VAL_DATE.isoformat()}:provider-main",
        source="provider-main",
        source_record_id=f"valuation-{asset_code}",
        fact_table="data_center_valuation_fact",
        fact_pk=fact_pk,
        observed_at=datetime.combine(VAL_DATE, datetime.min.time(), tzinfo=UTC),
        raw_payload_hash="a" * 64,
        quality_status="available_at_unverified",
    )


def test_valuation_publication_uses_val_date_and_exact_members() -> None:
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    publication = use_case.execute(
        [_fact()],
        provider_name="provider-main",
        published_at=PUBLISHED_AT,
    )

    assert publication is not None
    expected_as_of = datetime.combine(VAL_DATE, datetime.min.time(), tzinfo=UTC)
    assert publication.as_of == expected_as_of
    assert publication.as_of != _fact().fetched_at
    assert publication.coverage.selected_count == 1
    assert repository.published[0][1][0].fact_pk == "201"
    assert repository.published[0][1][0].quality_status == "available_at_unverified"


def test_valuation_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_valuation_publication_fails_closed_below_coverage_policy() -> None:
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ")]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(
            [_fact("000001.SZ"), _fact("600000.SH")],
            provider_name="provider-main",
            published_at=PUBLISHED_AT,
        )


@pytest.mark.django_db
def test_valuation_repository_candidate_preserves_val_date_and_evidence() -> None:
    row = ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=VAL_DATE,
        pe_ttm=12.3,
        pb=1.7,
        source="provider-main",
        source_record_id="valuation-1",
        raw_payload_hash="b" * 64,
        available_at=None,
    )

    references = ValuationFactRepository().list_publication_candidates([_fact()])

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source_record_id == "valuation-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == datetime(2026, 8, 2, 16, tzinfo=UTC)
    assert references[0].observed_at != row.fetched_at
    assert references[0].quality_status == "available_at_unverified"


@pytest.mark.django_db
def test_valuation_repository_rejects_future_available_at() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=VAL_DATE,
        pe_ttm=12.3,
        source="provider-main",
        available_at=future,
    )

    with pytest.raises(ValueError, match="future"):
        ValuationFactRepository().list_publication_candidates([_fact()])


def test_sync_valuation_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_valuations(self, _asset_code, _start, _end) -> list[ValuationFact]:
            return [_fact()]

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
            self.saved: list[ValuationFact] = []

        def bulk_upsert(self, facts: list[ValuationFact]) -> int:
            self.saved.extend(facts)
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[ValuationFact], str]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append((list(facts), provider_name))
            return None

    provider_repo = _ProviderRepository()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncValuationUseCase(
        provider_repo=provider_repo,
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(
        SyncValuationRequest(
            provider_id=1,
            asset_code="000001.SZ",
            start=VAL_DATE,
            end=VAL_DATE,
        )
    )

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]


def test_sync_current_valuation_batch_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_valuations(self, _asset_code, _start, _end) -> list[ValuationFact]:
            return [_fact()]

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
        def bulk_upsert(self, facts: list[ValuationFact]) -> int:
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[ValuationFact], str]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append((list(facts), provider_name))
            return None

    publisher = _Publisher()
    result = SyncCurrentValuationBatchUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(),
        fact_repo=_Facts(),
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(provider_id=1, asset_codes=["000001.SZ"], as_of_date=VAL_DATE)

    assert result.status == "success"
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0][0].asset_code == "000001.SZ"
    assert publisher.calls[0][1] == "provider-main"


def test_current_valuation_batch_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_current_valuations(self, _asset_codes, _as_of_date) -> list[ValuationFact]:
            return [_fact()]

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
            self.saved: list[ValuationFact] = []

        def bulk_upsert(self, facts: list[ValuationFact]) -> int:
            self.saved.extend(facts)
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[ValuationFact], str]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append((list(facts), provider_name))
            return None

    facts = _Facts()
    publisher = _Publisher()
    result = SyncCurrentValuationBatchUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(
        provider_id=1,
        asset_codes=["000001.SZ"],
        as_of_date=VAL_DATE,
    )

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]
