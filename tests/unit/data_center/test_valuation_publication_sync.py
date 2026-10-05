from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.batch_identity import ProviderAssetIdentityError
from apps.data_center.application.current_valuation_sync import SyncCurrentValuationBatchUseCase
from apps.data_center.application.dtos import SyncValuationBatchResult, SyncValuationRequest
from apps.data_center.application.publication_sync import PublishValuationBatchUseCase
from apps.data_center.application.sync_identity import build_sync_execution_identity
from apps.data_center.application.sync_use_cases import SyncValuationUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
)
from apps.data_center.domain.entities import (
    ProviderConfig,
    RawAudit,
    RawAuditReference,
    ValuationFact,
    raw_audit_content_hash,
)
from apps.data_center.infrastructure.fundamental_fact_repositories import ValuationFactRepository
from apps.data_center.infrastructure.models import ValuationFactModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
VAL_DATE = date(2026, 8, 3)
OBSERVED_AT = datetime(2026, 8, 3, 8, 14, 36, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def __init__(self, *, policy_version: str = "legacy") -> None:
        self.policy_version = policy_version

    def get_active(self, _dataset_key: str) -> PublicationPolicy:
        required_evidence = (
            ("source", "observed_at", "payload_hash")
            if self.policy_version == "legacy"
            else (
                "source",
                "observed_at",
                "available_at",
                "fetched_at",
                "raw_payload_hash",
                "raw_payload_scope",
            )
        )
        return PublicationPolicy(
            dataset=DatasetKey("equity.valuation.fact", "1.0", "1.0"),
            minimum_coverage_ratio=0.99,
            allow_partial=True,
            conflict_action="quarantine",
            required_evidence=required_evidence,
            retention_days=3650,
            policy_version=self.policy_version,
        )


class _PublicationRepository:
    def __init__(self) -> None:
        self.current: CanonicalPublication | None = None
        self.published: list[tuple[CanonicalPublication, tuple[PublicationMember, ...]]] = []
        self.members: dict[str, tuple[PublicationMember, ...]] = {}

    def get_current(self, _dataset_key: str, _publication_key: str) -> CanonicalPublication | None:
        return self.current

    def publish_with_members(
        self,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> CanonicalPublication:
        self.current = publication
        self.members[publication.publication_id] = members
        self.published.append((publication, members))
        return publication

    def list_members(self, publication_id: str) -> list[PublicationMember]:
        return list(self.members.get(publication_id, ()))


def _fact(asset_code: str = "000001.SZ") -> ValuationFact:
    return ValuationFact(
        asset_code=asset_code,
        val_date=VAL_DATE,
        pe_ttm=12.3,
        pb=1.7,
        source="provider-main",
        observed_at=OBSERVED_AT,
        available_at=AVAILABLE_AT,
        fetched_at=FETCHED_AT,
    )


class _SyncUnitOfWork:
    def __init__(self) -> None:
        self.active = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        assert not self.active
        self.active = True
        try:
            yield
        finally:
            self.active = False


class _SyncIdentityIssuer:
    def __init__(self, unit_of_work: _SyncUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def issue(self, *, dataset_key: str, provider_name: str):
        assert self.unit_of_work.active
        return build_sync_execution_identity(
            run_id="11111111-1111-4111-8111-111111111111",
            ingested_run_id="22222222-2222-4222-8222-222222222222",
            batch_id="33333333-3333-4333-8333-333333333333",
            dataset_key=dataset_key,
            provider_name=provider_name,
        )


class _SyncAuditWriter:
    def __init__(self, unit_of_work: _SyncUnitOfWork) -> None:
        self.unit_of_work = unit_of_work
        self.observations = []

    def write(self, observation) -> None:
        assert self.unit_of_work.active
        self.observations.append(observation)


class _SyncClock:
    def now(self) -> datetime:
        return FETCHED_AT


class _PersistedRawAuditRepository:
    def __init__(self, unit_of_work: _SyncUnitOfWork) -> None:
        self.unit_of_work = unit_of_work
        self.rows: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        assert self.unit_of_work.active
        persisted = replace(
            audit,
            raw_audit_id=f"raw-valuation-{len(self.rows) + 1}",
            content_hash=raw_audit_content_hash(audit),
        )
        self.rows.append(persisted)
        return persisted


class _SyncLineageDependencies:
    def __init__(self) -> None:
        self.unit_of_work = _SyncUnitOfWork()
        self.identity_issuer = _SyncIdentityIssuer(self.unit_of_work)
        self.fetch_audit_writer = _SyncAuditWriter(self.unit_of_work)
        self.raw_audit_repository = _PersistedRawAuditRepository(self.unit_of_work)
        self.clock = _SyncClock()


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
        observed_at=OBSERVED_AT,
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        available_at=AVAILABLE_AT,
        fetched_at=FETCHED_AT,
        raw_payload_scope="batch_response_body",
        fact_content_hash="b" * 64,
    )


@pytest.mark.parametrize(
    "policy_version,expected", [("legacy", "logical-adapter"), ("2", "provider-main")]
)
def test_publication_tracks_actual_fallback_source_under_versioned_policy(
    policy_version, expected
) -> None:
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version=policy_version),
    )
    publication = use_case.execute(
        [_fact()], provider_name="logical-adapter", published_at=PUBLISHED_AT
    )
    assert publication is not None
    assert publication.selected_source == expected


def test_versioned_publication_summarizes_all_selected_vendor_sources() -> None:
    fallback = replace(
        _reference("000002.SZ", "202"),
        source="provider-fallback",
        natural_key=f"000002.SZ:{VAL_DATE.isoformat()}:provider-fallback",
    )
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference(), fallback]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )
    publication = use_case.execute(
        [_fact(), replace(_fact("000002.SZ"), source="provider-fallback")],
        provider_name="logical-adapter",
        published_at=PUBLISHED_AT,
    )
    assert publication is not None
    assert publication.selected_source == "provider-fallback,provider-main"


def test_valuation_publication_uses_source_observed_at_and_exact_members() -> None:
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
    expected_as_of = OBSERVED_AT
    assert publication.as_of == expected_as_of
    assert publication.as_of != _fact().fetched_at
    assert publication.coverage.selected_count == 1
    assert repository.published[0][1][0].fact_pk == "201"
    assert repository.published[0][1][0].quality_status == "accepted"
    assert repository.published[0][1][0].available_at == AVAILABLE_AT
    assert repository.published[0][1][0].fetched_at == FETCHED_AT
    assert repository.published[0][1][0].raw_payload_scope == "batch_response_body"
    assert repository.published[0][1][0].fact_content_hash == "b" * 64


def test_valuation_publication_is_idempotent_for_identical_valid_snapshot() -> None:
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_valuation_publication_rejects_unverified_evidence() -> None:
    repository = _PublicationRepository()
    use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository(
            [replace(_reference(), quality_status="available_at_unverified")]
        ),
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )

    with pytest.raises(ValueError, match="quality"):
        use_case.execute(
            [_fact()],
            provider_name="provider-main",
            published_at=PUBLISHED_AT,
        )

    assert repository.published == []


def test_p2_policy_upgrade_does_not_reuse_legacy_idempotence_path() -> None:
    repository = _PublicationRepository()
    legacy_use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )
    versioned_use_case = PublishValuationBatchUseCase(
        fact_repository=_CandidateRepository([_reference()]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )

    legacy = legacy_use_case.execute(
        [_fact()], provider_name="provider-main", published_at=PUBLISHED_AT
    )
    versioned = versioned_use_case.execute(
        [_fact()], provider_name="provider-main", published_at=PUBLISHED_AT
    )

    assert legacy is not None
    assert versioned is not None
    assert versioned is not legacy
    assert legacy.policy_version == "1.0:1.0"
    assert versioned.policy_version.startswith("p2:2:")
    assert len(repository.published) == 2


def test_versioned_metadata_change_creates_new_publication() -> None:
    repository = _PublicationRepository()
    candidates = _CandidateRepository([_reference()])
    use_case = PublishValuationBatchUseCase(
        fact_repository=candidates,
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )

    first = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    candidates.references = [replace(_reference(), fetched_at=FETCHED_AT + timedelta(minutes=1))]
    second = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is not None
    assert second is not None
    assert second is not first
    assert second.publication_hash != first.publication_hash
    assert len(repository.published) == 2


def test_required_availability_cannot_borrow_current_snapshot() -> None:
    repository = _PublicationRepository()
    candidates = _CandidateRepository([_reference()])
    use_case = PublishValuationBatchUseCase(
        fact_repository=candidates,
        publication_repository=repository,
        policy_repository=_PolicyRepository(policy_version="2"),
    )

    current = use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)
    candidates.references = [replace(_reference(), available_at=None)]

    with pytest.raises(ValueError, match="available_at"):
        use_case.execute([_fact()], provider_name="provider-main", published_at=PUBLISHED_AT)

    assert current is not None
    assert repository.current is current
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
def test_valuation_repository_candidate_preserves_source_observed_at_and_evidence() -> None:
    row = ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=VAL_DATE,
        pe_ttm=12.3,
        pb=1.7,
        source="provider-main",
        source_record_id="valuation-1",
        raw_payload_hash="b" * 64,
        observed_at=OBSERVED_AT,
        available_at=None,
    )

    references = ValuationFactRepository().list_publication_candidates([_fact()])

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source_record_id == "valuation-1"
    assert references[0].raw_payload_hash == "b" * 64
    assert references[0].observed_at == OBSERVED_AT
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
        observed_at=OBSERVED_AT,
        available_at=future,
    )

    with pytest.raises(ValueError, match="future"):
        ValuationFactRepository().list_publication_candidates([_fact()])


@pytest.mark.django_db
def test_valuation_repository_rejects_missing_observed_at() -> None:
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=VAL_DATE,
        pe_ttm=12.3,
        source="provider-main",
        available_at=None,
    )

    with pytest.raises(ValueError, match="observed_at"):
        ValuationFactRepository().list_publication_candidates([_fact()])


def test_valuation_fact_rejects_naive_observed_at() -> None:
    with pytest.raises(ValueError, match="observed_at.*timezone"):
        ValuationFact(
            asset_code="000001.SZ",
            val_date=VAL_DATE,
            source="provider-main",
            observed_at=datetime(2026, 8, 3, 8, 14, 36),
            fetched_at=PUBLISHED_AT,
        )


def test_valuation_fact_rejects_fetched_at_before_observed_at() -> None:
    with pytest.raises(ValueError, match="fetched_at.*precede"):
        ValuationFact(
            asset_code="000001.SZ",
            val_date=VAL_DATE,
            source="provider-main",
            observed_at=OBSERVED_AT,
            fetched_at=OBSERVED_AT - timedelta(seconds=1),
        )


@pytest.mark.django_db
def test_valuation_repository_rejects_future_observed_at() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=VAL_DATE,
        pe_ttm=12.3,
        source="provider-main",
        observed_at=future,
        fetched_at=future + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="observed_at.*future"):
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


def test_sync_current_valuation_batch_audits_allowed_partial_coverage_as_ok() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_valuations(self, asset_code, _start, _end) -> list[ValuationFact]:
            return [replace(_fact(), source="tushare")] if asset_code == "000001.SZ" else []

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

    lineage = _SyncLineageDependencies()
    provider_repository = _ProviderRepository()
    publisher = _Publisher()
    result = SyncCurrentValuationBatchUseCase(
        provider_repo=provider_repository,
        provider_registry=_Registry(),
        fact_repo=_Facts(),
        raw_audit_repo=lineage.raw_audit_repository,
        publication_publisher=publisher,
        sync_identity_issuer=lineage.identity_issuer,
        sync_unit_of_work=lineage.unit_of_work,
        data_fetch_audit_writer=lineage.fetch_audit_writer,
        clock=lineage.clock,
    ).execute(
        provider_id=1,
        asset_codes=["000001.SZ", "600000.SH"],
        as_of_date=VAL_DATE,
    )

    assert result.status == "partial"
    assert result.returned_asset_codes == ("000001.SZ",)
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0][0].asset_code == "000001.SZ"
    assert publisher.calls[0][1] == "provider-main"
    assert lineage.raw_audit_repository.rows[0].status == "ok"
    assert lineage.fetch_audit_writer.observations[0].outcome.value == "success"
    health_metric = provider_repository.config.extra_config["health_metrics"]["valuation"]
    assert health_metric["last_status"] == "healthy"
    assert health_metric["consecutive_failures"] == 0
    assert health_metric["last_output_count"] == 1


def test_current_valuation_batch_invokes_publication_after_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_current_valuations(self, _asset_codes, _as_of_date) -> list[ValuationFact]:
            return [replace(_fact(), source="tushare")]

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

    lineage = _SyncLineageDependencies()
    facts = _Facts()
    publisher = _Publisher()
    result = SyncCurrentValuationBatchUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=lineage.raw_audit_repository,
        publication_publisher=publisher,
        sync_identity_issuer=lineage.identity_issuer,
        sync_unit_of_work=lineage.unit_of_work,
        data_fetch_audit_writer=lineage.fetch_audit_writer,
        clock=lineage.clock,
    ).execute(
        provider_id=1,
        asset_codes=["000001.SZ"],
        as_of_date=VAL_DATE,
    )

    assert result.status == "success"
    assert len(facts.saved) == 1
    assert facts.saved[0].ingested_run_id == "22222222-2222-4222-8222-222222222222"
    assert result.run_id == "11111111-1111-4111-8111-111111111111"
    assert result.ingested_run_id == facts.saved[0].ingested_run_id
    assert result.raw_audit_reference == lineage.raw_audit_repository.rows[0].exact_reference()
    assert result.to_dict()["raw_audit_reference"]["raw_audit_id"] == "raw-valuation-1"
    assert result.fact_source_type == "tushare"
    assert lineage.raw_audit_repository.rows[0].extra == {
        "source_type": "tushare",
        "provider_source_type": "tushare",
    }
    assert publisher.calls == [(facts.saved, "provider-main")]


def test_single_valuation_rejects_provider_substitution_before_fact_write(mocker) -> None:
    provider = mocker.Mock()
    provider.provider_name.return_value = "provider-main"
    provider.fetch_valuations.return_value = [_fact(asset_code="600000.SH")]
    provider_repo = mocker.Mock()
    provider_repo.get_by_id.return_value = ProviderConfig(
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
    registry = mocker.Mock()
    registry.get_by_id.return_value = provider
    registry.get_all_statuses.return_value = []
    facts = mocker.Mock()
    raw_audit = mocker.Mock()
    use_case = SyncValuationUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=facts,
        raw_audit_repo=raw_audit,
    )

    with pytest.raises(
        ProviderAssetIdentityError,
        match="valuation provider asset identities mismatch",
    ):
        use_case.execute(
            SyncValuationRequest(
                provider_id=1,
                asset_code="000001.SZ",
                start=VAL_DATE,
                end=VAL_DATE,
            )
        )

    facts.bulk_upsert.assert_not_called()


def test_strict_current_valuation_identity_rejects_substitution_before_fact_write() -> None:
    class _Provider:
        def provider_name(self) -> str:
            return "provider-main"

        def fetch_current_valuations(self, _asset_codes, _as_of_date) -> list[ValuationFact]:
            return [replace(_fact(asset_code="600000.SH"), source="tushare")]

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
            self.calls: list[list[ValuationFact]] = []

        def execute(self, facts, *, provider_name: str):
            self.calls.append(list(facts))
            return None

    lineage = _SyncLineageDependencies()
    facts = _Facts()
    publisher = _Publisher()
    use_case = SyncCurrentValuationBatchUseCase(
        provider_repo=_ProviderRepository(),
        provider_registry=_Registry(),
        fact_repo=facts,
        raw_audit_repo=lineage.raw_audit_repository,
        publication_publisher=publisher,
        sync_identity_issuer=lineage.identity_issuer,
        sync_unit_of_work=lineage.unit_of_work,
        data_fetch_audit_writer=lineage.fetch_audit_writer,
        clock=lineage.clock,
    )

    with pytest.raises(
        ProviderAssetIdentityError,
        match="valuation provider asset identities mismatch",
    ):
        use_case.execute(
            provider_id=1,
            asset_codes=["000001.SZ"],
            as_of_date=VAL_DATE,
            require_exact_asset_codes=True,
        )

    assert facts.saved == []
    assert publisher.calls == []
    assert lineage.raw_audit_repository.rows[0].status == "error"
    assert lineage.fetch_audit_writer.observations[0].outcome.value == "failed"


def test_valuation_batch_result_rejects_empty_or_mismatched_lineage() -> None:
    reference = RawAuditReference(
        raw_audit_id="raw-valuation-1",
        version="1",
        content_hash="a" * 64,
        run_id="11111111-1111-4111-8111-111111111111",
        ingested_run_id="22222222-2222-4222-8222-222222222222",
    )

    with pytest.raises(ValueError, match="run_id must be non-empty"):
        SyncValuationBatchResult(
            domain="valuation",
            provider_name="provider-main",
            stored_count=1,
            status="success",
            succeeded_asset_codes=["000001.SZ"],
            run_id="",
            ingested_run_id=reference.ingested_run_id,
            raw_audit_reference=reference,
        )

    with pytest.raises(ValueError, match="does not match the result"):
        SyncValuationBatchResult(
            domain="valuation",
            provider_name="provider-main",
            stored_count=1,
            status="success",
            succeeded_asset_codes=["000001.SZ"],
            run_id="44444444-4444-4444-8444-444444444444",
            ingested_run_id=reference.ingested_run_id,
            raw_audit_reference=reference,
        )

    with pytest.raises(ValueError, match="actual fact source type"):
        SyncValuationBatchResult(
            domain="valuation",
            provider_name="provider-main",
            stored_count=1,
            status="success",
            succeeded_asset_codes=["000001.SZ"],
            run_id=reference.run_id,
            ingested_run_id=reference.ingested_run_id,
            raw_audit_reference=reference,
        )
