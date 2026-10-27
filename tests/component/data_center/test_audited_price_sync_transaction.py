"""SQL proof that an audited price sync commits or rolls back as one unit."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from django.utils import timezone

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
from apps.data_center.application.price_response_capture import (
    CapturedPriceBarResponse,
    ExactPriceBarRequestScope,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import PublishPriceBarBatchUseCase
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.application.quote_response_capture import (
    ProviderResponsePayloadRetainerProtocol,
)
from apps.data_center.application.sync_use_cases import SyncPriceUseCase
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    RawAuditModel,
    RawPayloadModel,
    SyncExecutionIdentityModel,
)
from apps.data_center.infrastructure.models import PriceBarModel, ProviderConfigModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.provider_state_repositories import (
    ProviderConfigRepository,
    RawAuditRepository,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from core.exceptions import DataFetchError
from tests.api.test_fee_correction_flow_api import (  # noqa: F401
    seed_authority_generation_for_nomigrations_sqlite,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.data_center", "apps.audit"]
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
BAR_DATE = date(2026, 8, 25)
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    ProviderConfigModel,
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    PriceBarModel,
    SyncExecutionIdentityModel,
    RawAuditModel,
    RawPayloadModel,
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
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


@pytest.fixture(autouse=True)
def _freeze_orm_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ORM auto timestamps at the same controlled instant as the sync clock."""

    monkeypatch.setattr(timezone, "now", lambda: NOW)


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


class _ExactPriceProvider:
    """Configured provider fake that records exact daily calls without network I/O."""

    def __init__(self, response: CapturedPriceBarResponse | None = None) -> None:
        self.response = response
        self.calls: list[tuple[str, date]] = []

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
        del asset_code, start, end
        raise AssertionError("exact daily sync must not call historical fallback")

    def fetch_price_bar_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceBarResponse:
        self.calls.append((asset_code, target_trade_date))
        if self.response is None:
            raise AssertionError("test response was not configured")
        return self.response


class _HistoryOnlyTrackingProvider(_Provider):
    def __init__(self) -> None:
        self.history_calls = 0

    def fetch_price_history(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> list[PriceBar]:
        self.history_calls += 1
        return super().fetch_price_history(asset_code, start, end)


class _RetainerAfterSaveFailure:
    def __init__(self, delegate: RetainProviderResponsePayloadUseCase) -> None:
        self._delegate = delegate

    def execute(self, *args: object, **kwargs: object) -> ProviderResponsePayloadReference:
        self._delegate.execute(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("failure after raw payload retention")


class _RetainerWrongReference:
    def __init__(self, delegate: RetainProviderResponsePayloadUseCase) -> None:
        self._delegate = delegate

    def execute(self, *args: object, **kwargs: object) -> ProviderResponsePayloadReference:
        reference = self._delegate.execute(*args, **kwargs)  # type: ignore[arg-type]
        return dataclasses.replace(reference, provider_name="provider-substituted")


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
    DatasetContractModel._default_manager.create(
        dataset_key="equity.price.bar",
        contract_version="1.0",
        schema_version="1.0",
        owner="data_center",
        frequency="daily",
        decision_critical=False,
        fields=[{"name": "bar_date", "value_type": "date"}],
        freshness_seconds=604_800,
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
    provider_id: int | None = None,
    publication_key: str = "current",
    quality_audit_writer: (
        AppendDataQualityAuditObservationUseCase | _FailingQualityAuditWriter | None
    ) = None,
    degraded_quality: bool = False,
) -> tuple[SyncPriceUseCase, int]:
    resolved_provider_id = provider_id if provider_id is not None else _seed_contracts()
    provider_repo = ProviderConfigRepository()
    provider_repo._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    registry = ProviderRegistry()
    registry.register(
        _Provider(),
        priority=1,
        provider_id=resolved_provider_id,
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
            publication_key=publication_key,
        ),
        resolved_provider_id,
    )


def _exact_capture(
    provider_id: int, *, captured_provider_id: int | None = None
) -> CapturedPriceBarResponse:
    """Build a real-byte-shaped Tushare daily response for transaction tests."""

    asset_code = "000001.SZ"
    scope = ExactPriceBarRequestScope(
        provider_id=(captured_provider_id if captured_provider_id is not None else provider_id),
        provider_name="provider-main",
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code=asset_code,
        trade_date=BAR_DATE,
    )
    payload: dict[str, object] = {
        "code": 0,
        "msg": "",
        "data": {
            "fields": [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "amount",
            ],
            "items": [[asset_code, BAR_DATE.strftime("%Y%m%d"), 10, 11, 9.5, 10.5, 200, 2100]],
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    capture = ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=NOW,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    return CapturedPriceBarResponse(
        request_scope=scope,
        bar=PriceBar(
            asset_code=asset_code,
            bar_date=BAR_DATE,
            open=10.0,
            high=11.0,
            low=9.5,
            close=10.5,
            volume=20_000.0,
            amount=2_100_000.0,
            source="tushare",
            fetched_at=NOW,
        ),
        capture=capture,
    )


def _build_exact_use_case(
    audit_writer: AppendDataFetchAuditObservationUseCase | _FailAfterAuditWriter,
    *,
    provider: object,
    retainer: ProviderResponsePayloadRetainerProtocol | None,
) -> tuple[SyncPriceUseCase, int, RawLandingRepository]:
    """Use the existing real SQLite transaction fixture with exact-capture ports."""

    provider_id = _seed_contracts()
    provider_repo = ProviderConfigRepository()
    provider_repo._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    registry = ProviderRegistry()
    registry.register(
        provider,  # type: ignore[arg-type]
        priority=1,
        provider_id=provider_id,
        source_type="tushare",
    )
    fact_repo = PriceBarRepository()
    raw_audit_repo = RawAuditRepository()
    raw_payload_repo = RawLandingRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    publication_audit_writer = _canonical_publication_writer()
    quality_writer = _canonical_quality_writer()
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repo,
        quality_writer=quality_writer,
        clock=_Clock(),
    )
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        (
            provider_repo,
            fact_repo,
            raw_audit_repo,
            raw_payload_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        audit_writer,
        additional_audit_writers=(publication_audit_writer, quality_writer),
    )
    use_case = SyncPriceUseCase(
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
        publication_key="current",
        provider_response_payload_retainer=retainer,
    )
    return use_case, provider_id, raw_payload_repo


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


def test_independent_publication_preserves_current_pinned_price_fact_and_gate() -> None:
    current_use_case, provider_id = _build_use_case(_canonical_writer())
    current_result = current_use_case.execute(_request(provider_id))
    publications = CanonicalPublicationRepository()
    current_model = CanonicalPublicationModel._default_manager.get(publication_key="current")
    # The sync publisher persists immutable publication evidence; activation owns the pointer.
    CanonicalPublicationPointerModel._default_manager.create(
        dataset_key="equity.price.bar",
        publication_key="current",
        publication_id=current_model.publication_id,
        publication_hash=current_model.publication_hash,
    )
    current_before = publications.get_current("equity.price.bar", "current")
    assert current_result.status == "success"
    assert current_before is not None
    current_members_before = tuple(publications.list_members(current_before.publication_id))
    assert len(current_members_before) == 1
    current_member_before = current_members_before[0]
    fact_before = PriceBarModel._default_manager.get(pk=current_member_before.fact_pk)
    fact_hash_before = canonical_fact_content_hash(fact_before)

    preview_use_case, _ = _build_use_case(
        _canonical_writer(),
        provider_id=provider_id,
        publication_key="preview:m1",
    )
    preview_result = preview_use_case.execute(_request(provider_id))

    current_after = publications.get_current("equity.price.bar", "current")
    preview_after = CanonicalPublicationModel._default_manager.get(publication_key="preview:m1")
    assert preview_result.status == "success"
    assert current_after is not None
    assert preview_after is not None
    assert preview_after.state == PublicationState.PUBLISHED.value
    assert publications.get_current("equity.price.bar", "preview:m1") is None
    assert not CanonicalPublicationPointerModel._default_manager.filter(
        dataset_key="equity.price.bar",
        publication_key="preview:m1",
    ).exists()
    assert current_after.publication_id == current_before.publication_id
    assert current_after.publication_hash == current_before.publication_hash
    current_members_after = tuple(publications.list_members(current_after.publication_id))
    assert current_members_after == current_members_before
    current_fact_after = PriceBarModel._default_manager.get(pk=current_member_before.fact_pk)
    assert canonical_fact_content_hash(current_fact_after) == fact_hash_before
    assert current_fact_after.ingested_run_id == fact_before.ingested_run_id
    assert current_fact_after.revision_number == fact_before.revision_number
    preview_members = tuple(publications.list_members(str(preview_after.publication_id)))
    assert len(preview_members) == 1
    assert preview_members[0].fact_pk != current_member_before.fact_pk
    assert preview_members[0].observed_at == current_member_before.observed_at

    from apps.data_center.application import query_services

    current_gate = query_services.get_current_publication_gate(
        "equity.price.bar",
        "current",
        as_of=NOW,
        asset_code="000001.SZ",
    )
    assert current_gate is not None
    assert current_gate["must_not_use_for_decision"] is False


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


def test_error_quality_blocks_publication_but_commits_fetch_evidence() -> None:
    use_case, provider_id = _build_use_case(
        _canonical_writer(),
        degraded_quality=True,
    )

    with pytest.raises(ValueError, match="publication evidence quality is not publishable"):
        use_case.execute(_request(provider_id))

    identity = SyncExecutionIdentityModel._default_manager.get()
    fact = PriceBarModel._default_manager.get()
    raw_audit = RawAuditModel._default_manager.get()
    fetch_event = SystemAuditEventModel._default_manager.get(event_type="data.fetch.completed")
    blocked_event = SystemAuditEventModel._default_manager.get(
        event_type="data.publication.blocked"
    )
    fetch_outbox = SystemAuditOutboxModel._default_manager.get(event_id=fetch_event.event_id)
    blocked_outbox = SystemAuditOutboxModel._default_manager.get(event_id=blocked_event.event_id)
    assert fact.quality_status == "error"
    assert str(fact.ingested_run_id) == str(identity.ingested_run_id)
    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert raw_audit.status == "ok"
    assert raw_audit.row_count == 1
    assert fetch_event.outcome == "success"
    assert fetch_event.correlations["run_id"] == str(identity.run_id)
    assert fetch_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert fetch_event.resource_id == str(raw_audit.pk)
    assert fetch_event.evidence_refs[0]["content_hash"] == raw_audit.content_hash
    assert fetch_outbox.payload_hash == fetch_event.content_hash
    assert blocked_event.outcome == "blocked"
    assert blocked_event.severity == "critical"
    assert blocked_event.detail_schema == "data.publication.blocked.v1"
    assert blocked_event.detail["blocked_reason"] == "publication_policy_rejected"
    assert blocked_event.detail["error_class"] == "ValueError"
    assert blocked_event.correlations["run_id"] == str(identity.run_id)
    assert blocked_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert blocked_event.evidence_refs == [
        {
            "owner": "data_center",
            "artifact_type": "raw_audit",
            "artifact_id": str(raw_audit.pk),
            "artifact_version": "1",
            "content_hash": raw_audit.content_hash,
        }
    ]
    assert blocked_outbox.payload_hash == blocked_event.content_hash
    assert SyncExecutionIdentityModel._default_manager.count() == 1
    assert RawAuditModel._default_manager.count() == 1
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert not SystemAuditEventModel._default_manager.filter(
        event_type="data.publication.published"
    ).exists()
    assert not SystemAuditEventModel._default_manager.filter(
        event_type="data.quality.changed"
    ).exists()
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2
    provider = ProviderConfigModel._default_manager.get(pk=provider_id)
    assert provider.extra_config["provider_last_status"] == "healthy"
    assert provider.extra_config["provider_last_error"] == ""
    health = provider.extra_config["health_metrics"]["historical_price"]
    assert health["last_status"] == "healthy"
    assert health["last_output_count"] == 1
    assert health["consecutive_failures"] == 0


def test_legacy_unreliable_publication_records_warning_and_blocks_current_decision() -> None:
    """Historical error-quality publications can be audited but never serve decisions."""

    _seed_contracts()
    fact = PriceBarModel._default_manager.create(
        asset_code="000001.SZ",
        bar_date=BAR_DATE,
        freq="1d",
        adjustment=PriceAdjustment.NONE.value,
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        source="tushare",
        source_record_id="legacy-price-1",
        raw_payload_hash="a" * 64,
        quality_status="error",
        revision_number=1,
    )
    reference = PriceBarRepository().list_publication_candidates(
        [
            PriceBar(
                asset_code=fact.asset_code,
                bar_date=fact.bar_date,
                freq=fact.freq,
                adjustment=PriceAdjustment(fact.adjustment),
                open=float(fact.open),
                high=float(fact.high),
                low=float(fact.low),
                close=float(fact.close),
                source=fact.source,
                fetched_at=fact.fetched_at,
            )
        ]
    )[0]
    publication_id = str(uuid4())
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="equity.price.bar",
    )
    publication_digest = publication_hash((member_reference(member),))
    persisted_member = PublicationMemberModel._default_manager.create(
        member_id=member.member_id,
        publication_id=publication_id,
        dataset_key=member.dataset_key,
        natural_key=member.natural_key,
        source=member.source,
        source_record_id=member.source_record_id,
        fact_table=member.fact_table,
        fact_pk=member.fact_pk,
        observed_at=member.observed_at,
        raw_payload_hash=member.raw_payload_hash,
        quality_status=member.quality_status,
        revision_number=member.revision_number,
        available_at=member.available_at,
        fetched_at=member.fetched_at,
        source_published_at=member.source_published_at,
        raw_payload_scope=member.raw_payload_scope,
        fact_content_hash=member.fact_content_hash,
    )
    publication = CanonicalPublicationModel._default_manager.create(
        publication_id=publication_id,
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="1.0:1.0",
        state=PublicationState.PUBLISHED.value,
        selected_source="provider-main",
        publication_hash=publication_digest,
        member_count=1,
        conflict_count=0,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        coverage_missing_count=0,
        coverage_conflict_count=0,
        as_of=reference.observed_at,
        published_at=NOW,
        must_not_use_for_decision=False,
        created_by="legacy-fixture",
    )
    CoverageSnapshotModel._default_manager.create(
        coverage_id=str(uuid4()),
        publication_id=publication_id,
        requested_count=1,
        eligible_count=1,
        selected_count=1,
        missing_count=0,
        conflict_count=0,
        generated_at=NOW,
    )

    observation = RecordPublicationQualityUseCase(
        publication_reader=CanonicalPublicationRepository(),
        quality_writer=_canonical_quality_writer(),
        clock=_Clock(),
    ).execute(
        publication_id=publication_id,
        run_id=str(uuid4()),
        ingested_run_id=str(uuid4()),
        provider_key="provider-main",
    )

    quality_event = SystemAuditEventModel._default_manager.get(event_type="data.quality.changed")
    quality_outbox = SystemAuditOutboxModel._default_manager.get(event_id=quality_event.event_id)
    assert observation.quality_state == "degraded"
    assert observation.quality_status_counts[0].status == "degraded"
    assert observation.quality_status_counts[0].count == 1
    assert fact.quality_status == "error"
    assert persisted_member.quality_status == "error"
    assert persisted_member.fact_content_hash == member.fact_content_hash
    assert publication.publication_hash == publication_digest
    assert quality_event.outcome == "detected"
    assert quality_event.severity == "warning"
    assert quality_event.publication_id == publication_id
    assert quality_event.correlations["evidence_ref"] == publication_id
    assert quality_event.detail["quality_state"] == "degraded"
    assert quality_event.detail["quality_status_counts"] == [{"status": "degraded", "count": 1}]
    assert quality_event.evidence_refs == [
        {
            "owner": "data_center",
            "artifact_type": "canonical_publication",
            "artifact_id": publication_id,
            "artifact_version": publication.policy_version,
            "content_hash": publication_digest,
        }
    ]
    assert quality_outbox.payload_hash == quality_event.content_hash
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1

    from apps.data_center.application import query_services

    current_gate = query_services.get_current_publication_gate(
        "equity.price.bar",
        "current",
    )
    assert current_gate is None


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


def test_exact_daily_capture_commits_raw_payload_fact_publication_and_audit_binding() -> None:
    provider = _ExactPriceProvider()
    use_case, provider_id, raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )
    response = _exact_capture(provider_id)
    provider.response = response
    use_case._provider_response_payload_retainer = RetainProviderResponsePayloadUseCase(
        raw_payload_repo
    )

    result = use_case.execute_exact_daily(
        provider_id=provider_id,
        asset_code="000001.SZ",
        target_trade_date=BAR_DATE,
    )

    assert provider.calls == [("000001.SZ", BAR_DATE)]
    assert result.status == "success"
    assert result.stored_count == 1
    identity = SyncExecutionIdentityModel._default_manager.get()
    payload_model = RawPayloadModel._default_manager.get()
    raw_audit = RawAuditModel._default_manager.get()
    fact = PriceBarModel._default_manager.get()
    reference = ProviderResponsePayloadReference.from_payload(
        raw_audit.extra["provider_response_payload_reference"]
    )
    assert reference.verifies(payload_model.to_domain())
    assert payload_model.payload_hash == reference.payload_hash
    assert payload_model.run_id == identity.run_id
    assert raw_audit.response_payload_hash == reference.payload_hash
    assert raw_audit.extra["provider_response_request_scope"] == response.request_scope.to_payload()
    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert str(fact.ingested_run_id) == str(identity.ingested_run_id)
    assert fact.volume == 20_000.0
    assert fact.amount == 2_100_000.0
    raw_body = json.loads(response.capture.body)
    assert raw_body["data"]["items"][0][-2:] == [200, 2100]
    assert CanonicalPublicationModel._default_manager.count() == 1
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


@pytest.mark.parametrize("display_name", ["Tushare Pro", "provider-main"])
def test_exact_daily_versioned_publication_audits_fact_source(
    monkeypatch: pytest.MonkeyPatch, display_name: str
) -> None:
    """Commit exact captured prices when the provider label differs from its source key."""

    monkeypatch.setattr(_ExactPriceProvider, "provider_name", lambda self: display_name)
    provider = _ExactPriceProvider()
    use_case, provider_id, raw_payload_repo = _build_exact_use_case(
        _canonical_writer(), provider=provider, retainer=None
    )
    ProviderConfigModel._default_manager.filter(pk=provider_id).update(name=display_name)
    DatasetPublicationPolicyModel._default_manager.filter(
        dataset_key="equity.price.bar", active=True
    ).update(
        policy_version="quality-source-v1",
        required_evidence=["source", "observed_at", "payload_hash", "fact_content_hash"],
    )
    response = _exact_capture(provider_id)
    provider.response = dataclasses.replace(
        response,
        request_scope=dataclasses.replace(response.request_scope, provider_name=display_name),
    )
    use_case._provider_response_payload_retainer = RetainProviderResponsePayloadUseCase(
        raw_payload_repo
    )

    result = use_case.execute_exact_daily(
        provider_id=provider_id, asset_code="000001.SZ", target_trade_date=BAR_DATE
    )

    assert result.status == "success" and result.stored_count == 1
    assert provider.calls == [("000001.SZ", BAR_DATE)]
    publication = CanonicalPublicationModel._default_manager.get()
    assert publication.selected_source == "tushare"
    assert PriceBarModel._default_manager.get().source == "tushare"
    assert PublicationMemberModel._default_manager.count() == 1
    assert RawPayloadModel._default_manager.count() == 1
    assert RawAuditModel._default_manager.count() == 1
    assert SyncExecutionIdentityModel._default_manager.count() == 1
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2
    assert CanonicalPublicationPointerModel._default_manager.count() == 0


def test_exact_daily_without_capture_capability_does_not_call_history_fallback() -> None:
    provider = _HistoryOnlyTrackingProvider()
    use_case, provider_id, _raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )

    with pytest.raises(DataFetchError, match="exact daily"):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=BAR_DATE,
        )

    assert provider.history_calls == 0
    assert PriceBarModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0


def test_exact_daily_without_retainer_does_not_make_provider_request() -> None:
    provider = _ExactPriceProvider()
    use_case, provider_id, _raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )
    provider.response = _exact_capture(provider_id)

    with pytest.raises(DataFetchError, match="retention is not configured"):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=BAR_DATE,
        )

    assert provider.calls == []
    assert RawPayloadModel._default_manager.count() == 0
    assert PriceBarModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0


def test_exact_daily_invalid_asset_scope_is_rejected_before_provider_request() -> None:
    provider = _ExactPriceProvider()
    use_case, provider_id, _raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )
    provider.response = _exact_capture(provider_id)

    with pytest.raises(DataFetchError, match="request scope is invalid"):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="ABC",
            target_trade_date=BAR_DATE,
        )

    assert provider.calls == []
    assert PriceBarModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0


def test_exact_daily_rejects_capture_from_another_provider_before_fact_or_publication() -> None:
    provider = _ExactPriceProvider()
    use_case, provider_id, raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )
    provider.response = _exact_capture(provider_id, captured_provider_id=provider_id + 1)
    use_case._provider_response_payload_retainer = RetainProviderResponsePayloadUseCase(
        raw_payload_repo
    )

    with pytest.raises(DataFetchError):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=BAR_DATE,
        )

    assert provider.calls == [("000001.SZ", BAR_DATE)]
    assert RawPayloadModel._default_manager.count() == 0
    assert PriceBarModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0


@pytest.mark.parametrize(
    ("field_name", "mismatched_value"),
    [
        ("close", 10.25),
        ("volume", 20_001.0),
        ("amount", 2_100_001.0),
    ],
)
def test_exact_daily_rejects_normalized_bar_detached_from_captured_body(
    field_name: str, mismatched_value: float
) -> None:
    """A failed body-to-fact comparison writes only the normal failed-fetch audit."""

    provider = _ExactPriceProvider()
    use_case, provider_id, raw_payload_repo = _build_exact_use_case(
        _canonical_writer(),
        provider=provider,
        retainer=None,
    )
    response = _exact_capture(provider_id)
    mismatched_bar = dataclasses.replace(response.bar, **{field_name: mismatched_value})
    provider.response = dataclasses.replace(response, bar=mismatched_bar)
    use_case._provider_response_payload_retainer = RetainProviderResponsePayloadUseCase(
        raw_payload_repo
    )

    with pytest.raises(DataFetchError, match="normalized price bar"):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=BAR_DATE,
        )

    assert RawAuditModel._default_manager.count() == 1
    assert RawAuditModel._default_manager.get().status == "error"
    assert RawPayloadModel._default_manager.count() == 0
    assert PriceBarModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0


@pytest.mark.parametrize("failure", ["retainer", "reference", "audit"])
def test_exact_daily_commit_failure_rolls_back_all_capture_participants(failure: str) -> None:
    provider = _ExactPriceProvider()
    writer: AppendDataFetchAuditObservationUseCase | _FailAfterAuditWriter = _canonical_writer()
    if failure == "audit":
        writer = _FailAfterAuditWriter(_canonical_writer())
    use_case, provider_id, raw_payload_repo = _build_exact_use_case(
        writer,
        provider=provider,
        retainer=None,
    )
    response = _exact_capture(provider_id)
    provider.response = response
    delegate = RetainProviderResponsePayloadUseCase(raw_payload_repo)
    if failure == "retainer":
        use_case._provider_response_payload_retainer = _RetainerAfterSaveFailure(delegate)
        expected_error: type[BaseException] = RuntimeError
    elif failure == "reference":
        use_case._provider_response_payload_retainer = _RetainerWrongReference(delegate)
        expected_error = DataFetchError
    else:
        use_case._provider_response_payload_retainer = delegate
        expected_error = RuntimeError

    with pytest.raises(expected_error):
        use_case.execute_exact_daily(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=BAR_DATE,
        )

    assert provider.calls == [("000001.SZ", BAR_DATE)]
    assert RawPayloadModel._default_manager.count() == 0
    assert PriceBarModel._default_manager.count() == 0
    assert SyncExecutionIdentityModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
