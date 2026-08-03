from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.publication_sync import PublishFinancialBatchUseCase
from apps.data_center.application.sync_use_cases import SyncFinancialUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import FinancialFact, ProviderConfig
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.infrastructure.fundamental_fact_repositories import FinancialFactRepository
from apps.data_center.infrastructure.models import FinancialFactModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
PERIOD_END = date(2026, 6, 30)
AVAILABLE_AT = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("equity.financial.fact", "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=True,
            conflict_action="quarantine",
            required_evidence=("source", "observed_at", "available_at", "payload_hash"),
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


def _fact(
    asset_code: str = "000001.SZ",
    *,
    available_at: datetime | None = AVAILABLE_AT,
) -> FinancialFact:
    return FinancialFact(
        asset_code=asset_code,
        period_end=PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="revenue",
        value=123.4,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=available_at,
        fetched_at=PUBLISHED_AT,
    )


def _reference(
    asset_code: str = "000001.SZ",
    fact_pk: str = "201",
    *,
    observed_at: datetime = AVAILABLE_AT,
) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=(f"{asset_code}:{PERIOD_END.isoformat()}:quarterly:revenue:provider-main"),
        source="provider-main",
        source_record_id=f"financial-{asset_code}",
        fact_table="data_center_financial_fact",
        fact_pk=fact_pk,
        observed_at=observed_at,
        raw_payload_hash="a" * 64,
    )


def test_financial_publication_uses_available_at_and_exact_members() -> None:
    repository = _PublicationRepository()
    use_case = PublishFinancialBatchUseCase(
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
    assert publication.as_of == AVAILABLE_AT
    assert publication.as_of != _fact().fetched_at
    assert publication.coverage.selected_count == 1
    assert publication.coverage.missing_count == 0
    assert repository.published[0][1][0].fact_pk == "201"
    assert repository.published[0][1][0].observed_at == AVAILABLE_AT


def test_financial_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_financial_publication_fails_closed_below_coverage_policy() -> None:
    facts = [_fact("000001.SZ"), _fact("600000.SH")]
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ")]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(facts, provider_name="provider-main", published_at=PUBLISHED_AT)


def test_financial_publication_blocks_when_available_at_is_missing() -> None:
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="available_at"):
        use_case.execute(
            [_fact(available_at=None)],
            provider_name="provider-main",
            published_at=PUBLISHED_AT,
        )


def test_financial_publication_rejects_future_available_at() -> None:
    future = datetime(2026, 8, 5, tzinfo=UTC)
    use_case = PublishFinancialBatchUseCase(
        fact_repository=_CandidateRepository([_reference(observed_at=future)]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="availability"):
        use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)


@pytest.mark.django_db
def test_financial_repository_candidate_requires_available_at_and_preserves_evidence() -> None:
    missing = FinancialFactModel.objects.create(
        asset_code="600000.SH",
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="revenue",
        value=120,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=None,
        source_record_id="missing-available",
    )
    row = FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="revenue",
        value=123.4,
        unit="元",
        source="provider-main",
        report_date=date(2026, 7, 30),
        available_at=AVAILABLE_AT,
        source_record_id="financial-1",
        raw_payload_hash="b" * 64,
    )

    references = FinancialFactRepository().list_publication_candidates(
        [_fact(), _fact("600000.SH", available_at=None)]
    )

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source == "provider-main"
    assert references[0].source_record_id == "financial-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == AVAILABLE_AT
    assert references[0].observed_at != row.fetched_at
    assert str(missing.pk) not in {reference.fact_pk for reference in references}


def test_sync_financial_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_financials(self, _asset_code, periods: int = 8) -> list[FinancialFact]:
            return [_fact()][:periods]

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
            self.saved: list[FinancialFact] = []

        def bulk_upsert(self, facts: list[FinancialFact]) -> int:
            self.saved.extend(facts)
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[FinancialFact], str]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append((list(facts), provider_name))
            return None

    provider_repo = _ProviderRepository()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncFinancialUseCase(
        provider_repo=provider_repo,
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(SyncFinancialRequest(provider_id=1, asset_code="000001.SZ", periods=1))

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert publisher.calls == [(facts.saved, "provider-main")]
