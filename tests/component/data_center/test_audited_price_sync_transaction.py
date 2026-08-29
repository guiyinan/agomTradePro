"""SQLite proof that an audited price sync commits or rolls back as one unit."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from apps.audit.application.data_fetch_audit import (
    AppendDataFetchAuditObservationUseCase,
    DataFetchAuditObservation,
)
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
)
from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
    DataQualityAuditObservation,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.dtos import SyncPriceRequest
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import PublishPriceBarBatchUseCase
from apps.data_center.application.sync_use_cases import SyncPriceUseCase
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    RawAuditModel,
    SyncExecutionIdentityModel,
)
from apps.data_center.infrastructure.models import PriceBarModel, ProviderConfigModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.provider_state_repositories import (
    ProviderConfigRepository,
    RawAuditRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
BAR_DATE = date(2026, 8, 25)
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    ProviderConfigModel,
    DatasetPublicationPolicyModel,
    PriceBarModel,
    SyncExecutionIdentityModel,
    RawAuditModel,
    CanonicalPublicationModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    SystemAuditEventModel,
    SystemAuditOutboxModel,
)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Isolate only the tables participating in this transaction proof."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(SCHEMA_MODELS):
            yield


class _Provider:
    def provider_name(self) -> str:
        return "provider-main"

    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.HISTORICAL_PRICE

    def fetch_price_history(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> list[PriceBar]:
        assert asset_code == "000001.SZ"
        assert start <= BAR_DATE <= end
        return [
            PriceBar(
                asset_code=asset_code,
                bar_date=BAR_DATE,
                open=10.0,
                high=11.0,
                low=9.5,
                close=10.5,
                freq="1d",
                adjustment=PriceAdjustment.NONE,
                source="tushare",
                fetched_at=NOW,
            )
        ]


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _Clock:
    def now(self) -> datetime:
        return NOW


class _EmptyCredentialStore:
    def resolve(self, _provider: ProviderConfigModel) -> tuple[str, str, str]:
        return "", "", ""

    def has_record(self, _provider: ProviderConfigModel) -> bool:
        return False

    def persist(
        self,
        _provider: ProviderConfigModel,
        *,
        api_key: str | None,
        api_secret: str | None,
    ) -> str:
        del api_key, api_secret
        return ""


class _FailAfterAuditWriter:
    def __init__(self, delegate: AppendDataFetchAuditObservationUseCase) -> None:
        self._delegate = delegate

    @property
    def database_alias(self) -> str:
        return self._delegate.database_alias

    def write(self, observation: DataFetchAuditObservation) -> None:
        self._delegate.write(observation)
        raise RuntimeError("failure after canonical audit append")


class _FailingQualityAuditWriter:
    """Required quality writer that fails after publication persistence."""

    database_alias = "default"

    def write(self, observation: DataQualityAuditObservation) -> None:
        del observation
        raise RuntimeError("quality audit backend failure")


class _DegradedPriceBarRepository(PriceBarRepository):
    """Persist the provider row with an explicitly degraded quality status."""

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        count = super().bulk_upsert(bars)
        PriceBarModel._default_manager.update(quality_status="error")
        return count


def _seed_contracts() -> int:
    provider = ProviderConfigModel._default_manager.create(
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    DatasetPublicationPolicyModel._default_manager.create(
        dataset_key="equity.price.bar",
        contract_version="1.0",
        schema_version="1.0",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "observed_at", "payload_hash"],
        retention_days=3650,
        active=True,
    )
    assert provider.pk is not None
    return int(provider.pk)


def _canonical_writer() -> AppendDataFetchAuditObservationUseCase:
    return AppendDataFetchAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_publication_writer() -> AppendDataPublicationAuditObservationUseCase:
    return AppendDataPublicationAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_quality_writer() -> AppendDataQualityAuditObservationUseCase:
    return AppendDataQualityAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _build_use_case(
    audit_writer: AppendDataFetchAuditObservationUseCase | _FailAfterAuditWriter,
    *,
    quality_audit_writer: (
        AppendDataQualityAuditObservationUseCase | _FailingQualityAuditWriter | None
    ) = None,
    degraded_quality: bool = False,
) -> tuple[SyncPriceUseCase, int]:
    provider_id = _seed_contracts()
    provider_repo = ProviderConfigRepository()
    provider_repo._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    registry = ProviderRegistry()
    registry.register(
        _Provider(),
        priority=1,
        provider_id=provider_id,
        source_type="tushare",
    )
    fact_repo = _DegradedPriceBarRepository() if degraded_quality else PriceBarRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    publication_audit_writer = _canonical_publication_writer()
    resolved_quality_writer = quality_audit_writer or _canonical_quality_writer()
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repo,
        quality_writer=resolved_quality_writer,
        clock=_Clock(),
    )
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        (
            provider_repo,
            fact_repo,
            raw_audit_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        audit_writer,
        additional_audit_writers=(publication_audit_writer, resolved_quality_writer),
    )
    return (
        SyncPriceUseCase(
            provider_repo=provider_repo,
            provider_registry=registry,
            fact_repo=fact_repo,
            raw_audit_repo=raw_audit_repo,
            publication_publisher=PublishPriceBarBatchUseCase(
                fact_repository=fact_repo,
                publication_repository=publication_repo,
                policy_repository=policy_repo,
            ),
            sync_identity_issuer=DjangoSyncExecutionIdentityIssuer(identity_repo),
            sync_unit_of_work=unit_of_work,
            data_fetch_audit_writer=audit_writer,
            data_publication_audit_writer=publication_audit_writer,
            publication_quality_recorder=quality_recorder,
            clock=_Clock(),
        ),
        provider_id,
    )


def _request(provider_id: int) -> SyncPriceRequest:
    return SyncPriceRequest(
        provider_id=provider_id,
        asset_code="000001.SZ",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
    )


def test_success_commits_correlated_fact_evidence_publication_events_and_outboxes() -> None:
    use_case, provider_id = _build_use_case(_canonical_writer())

    result = use_case.execute(_request(provider_id))

    assert result.status == "success"
    identity = SyncExecutionIdentityModel._default_manager.get()
    fact = PriceBarModel._default_manager.get()
    raw_audit = RawAuditModel._default_manager.get()
    publication = CanonicalPublicationModel._default_manager.get()
    fetch_event = SystemAuditEventModel._default_manager.get(event_type="data.fetch.completed")
    publication_event = SystemAuditEventModel._default_manager.get(
        event_type="data.publication.published"
    )
    fetch_outbox = SystemAuditOutboxModel._default_manager.get(event_id=fetch_event.event_id)
    publication_outbox = SystemAuditOutboxModel._default_manager.get(
        event_id=publication_event.event_id
    )
    assert str(fact.ingested_run_id) == str(identity.ingested_run_id)
    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert str(publication.run_id) == str(identity.run_id)
    assert fetch_event.correlations["run_id"] == str(identity.run_id)
    assert fetch_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert fetch_event.resource_id == str(raw_audit.pk)
    assert fetch_event.evidence_refs[0]["content_hash"] == raw_audit.content_hash
    assert fetch_event.scope_tenant_id == SCOPE.tenant_id
    assert fetch_event.scope_owner_id == SCOPE.owner_id
    assert publication_event.publication_id == str(publication.publication_id)
    assert publication_event.correlations["run_id"] == str(identity.run_id)
    assert publication_event.evidence_refs[0]["artifact_id"] == str(raw_audit.pk)
    assert fetch_outbox.payload_hash == fetch_event.content_hash
    assert publication_outbox.payload_hash == publication_event.content_hash
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2
    assert PublicationMemberModel._default_manager.count() == 1
    assert CoverageSnapshotModel._default_manager.count() == 1


def test_failure_after_audit_append_rolls_back_every_transaction_participant() -> None:
    writer = _FailAfterAuditWriter(_canonical_writer())
    use_case, provider_id = _build_use_case(writer)

    with pytest.raises(RuntimeError, match="failure after canonical audit append"):
        use_case.execute(_request(provider_id))

    assert PriceBarModel._default_manager.count() == 0
    assert SyncExecutionIdentityModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
    provider = ProviderConfigModel._default_manager.get(pk=provider_id)
    assert provider.extra_config == {}


def test_degraded_member_commits_exact_quality_transition_and_outbox() -> None:
    use_case, provider_id = _build_use_case(
        _canonical_writer(),
        degraded_quality=True,
    )

    result = use_case.execute(_request(provider_id))

    publication = CanonicalPublicationModel._default_manager.get()
    quality_event = SystemAuditEventModel._default_manager.get(event_type="data.quality.changed")
    quality_outbox = SystemAuditOutboxModel._default_manager.get(event_id=quality_event.event_id)
    assert result.publication_id == str(publication.publication_id)
    assert quality_event.outcome == "detected"
    assert quality_event.severity == "warning"
    assert quality_event.publication_id == str(publication.publication_id)
    assert quality_event.correlations["evidence_ref"] == str(publication.publication_id)
    assert quality_event.detail["quality_state"] == "degraded"
    assert quality_event.detail["quality_status_counts"] == [{"status": "degraded", "count": 1}]
    assert quality_event.evidence_refs == [
        {
            "owner": "data_center",
            "artifact_type": "canonical_publication",
            "artifact_id": str(publication.publication_id),
            "artifact_version": publication.policy_version,
            "content_hash": publication.publication_hash,
        }
    ]
    assert quality_outbox.payload_hash == quality_event.content_hash
    assert SystemAuditEventModel._default_manager.count() == 3
    assert SystemAuditOutboxModel._default_manager.count() == 3


def test_quality_writer_failure_rolls_back_fact_publication_events_and_outboxes() -> None:
    use_case, provider_id = _build_use_case(
        _canonical_writer(),
        quality_audit_writer=_FailingQualityAuditWriter(),
    )

    with pytest.raises(RuntimeError, match="quality audit backend failure"):
        use_case.execute(_request(provider_id))

    assert PriceBarModel._default_manager.count() == 0
    assert SyncExecutionIdentityModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
