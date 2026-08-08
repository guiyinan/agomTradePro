from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.dtos import SyncMacroRequest
from apps.data_center.application.macro_publication import PublishMacroBatchUseCase
from apps.data_center.application.sync_use_cases import SyncMacroUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import MacroFact, ProviderConfig
from apps.data_center.infrastructure.macro_fact_repositories import MacroFactRepository
from apps.data_center.infrastructure.models import MacroFactModel

PUBLISHED_AT = date(2026, 7, 31)
PUBLISH_TIME = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
REPORTING_PERIOD = date(2026, 6, 30)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("macro.fact", "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "observed_at", "published_at", "payload_hash"),
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


def _fact(indicator_code: str = "CN_CPI") -> MacroFact:
    return MacroFact(
        indicator_code=indicator_code,
        reporting_period=REPORTING_PERIOD,
        value=1.2,
        unit="%",
        source="provider-main",
        revision_number=1,
        published_at=PUBLISHED_AT,
        fetched_at=PUBLISH_TIME,
        extra={"source_type": "provider-main"},
    )


def _reference(indicator_code: str = "CN_CPI", fact_pk: str = "101") -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{indicator_code}:{REPORTING_PERIOD.isoformat()}:provider-main:1",
        source="provider-main",
        source_record_id=f"macro-{indicator_code}",
        fact_table="data_center_macro_fact",
        fact_pk=fact_pk,
        observed_at=datetime(2026, 7, 31, tzinfo=UTC),
        raw_payload_hash="a" * 64,
    )


def test_macro_publication_uses_source_published_at_and_exact_member() -> None:
    repository = _PublicationRepository()
    publication = PublishMacroBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    ).execute([_fact()], provider_name="provider-main", published_at=PUBLISH_TIME)

    assert publication is not None
    assert publication.as_of == datetime(2026, 7, 31, tzinfo=UTC)
    assert publication.as_of != _fact().fetched_at
    assert repository.published[0][1][0].fact_pk == "101"


def test_macro_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishMacroBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISH_TIME)
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISH_TIME)

    assert first is second
    assert len(repository.published) == 1


def test_macro_publication_blocks_missing_published_at_candidate() -> None:
    use_case = PublishMacroBatchUseCase(
        fact_repository=_CandidateRepository([]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="published_at"):
        use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISH_TIME)


@pytest.mark.django_db
def test_macro_repository_candidate_preserves_published_at_and_evidence() -> None:
    missing = MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=REPORTING_PERIOD,
        value=49.5,
        unit="指数",
        source="provider-main",
        revision_number=1,
        published_at=None,
    )
    row = MacroFactModel.objects.create(
        indicator_code="CN_CPI",
        reporting_period=REPORTING_PERIOD,
        value=1.2,
        unit="%",
        source="provider-main",
        revision_number=1,
        published_at=PUBLISHED_AT,
        source_record_id="macro-1",
        raw_payload_hash="b" * 64,
    )

    references = MacroFactRepository().list_publication_candidates([_fact(), _fact("CN_PMI")])

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source_record_id == "macro-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == datetime(2026, 7, 30, 16, tzinfo=UTC)
    assert str(missing.pk) not in {reference.fact_pk for reference in references}


def test_sync_macro_use_case_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_macro_series(self, _indicator_code, _start, _end) -> list[MacroFact]:
            return [_fact()]

    class _ProviderRepository:
        def __init__(self) -> None:
            self.config = ProviderConfig(
                id=1,
                name="provider-main",
                source_type="provider-main",
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

    class _Catalog:
        is_active = True
        default_period_type = "M"

    class _CatalogRepository:
        def get_by_code(self, _indicator_code: str):
            return _Catalog()

    class _Rule:
        id = 1
        storage_unit = "%"
        original_unit = "%"
        display_unit = "%"
        dimension_key = "rate"
        multiplier_to_storage = 1.0

    class _RuleRepository:
        def resolve_active_rule(self, *_args, **_kwargs):
            return _Rule()

    class _Facts:
        def bulk_upsert(self, facts: list[MacroFact]) -> int:
            return len(facts)

    class _RawAudit:
        def log(self, _audit) -> None:
            return None

    class _Publisher:
        def __init__(self) -> None:
            self.calls: list[tuple[list[MacroFact], str, str]] = []

        def execute(self, facts, *, provider_name: str, publication_key: str):
            self.calls.append((list(facts), provider_name, publication_key))
            return None

    publisher = _Publisher()
    result = SyncMacroUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(),
        fact_repo=_Facts(),
        catalog_repo=_CatalogRepository(),
        unit_rule_repo=_RuleRepository(),
        raw_audit_repo=_RawAudit(),
        publication_publisher=publisher,
    ).execute(
        SyncMacroRequest(
            provider_id=1,
            indicator_code="CN_CPI",
            start=REPORTING_PERIOD,
            end=REPORTING_PERIOD,
        )
    )

    assert result.status == "success"
    assert len(publisher.calls) == 1
    assert publisher.calls[0][1] == "provider-main"
    assert publisher.calls[0][2] == "CN_CPI"
