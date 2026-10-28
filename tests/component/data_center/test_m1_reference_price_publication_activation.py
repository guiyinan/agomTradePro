"""Contracts and end-to-end coverage for the isolated M1 close lane."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import apps.data_center.m1_reference_price_publication_composition as m1_composition
from apps.audit.application.data_fetch_audit import AppendDataFetchAuditObservationUseCase
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
)
from apps.audit.application.data_quality_audit import AppendDataQualityAuditObservationUseCase
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.control_plane import CanonicalPublicationRepositoryPort
from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationDataset,
)
from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationCandidateRepositoryProtocol,
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.m1_reference_price_publication import (
    M1ReferencePricePublicationCommand,
    M1ReferencePricePublicationUseCase,
)
from apps.data_center.application.price_response_capture import (
    CapturedPriceBarResponse,
    ExactPriceBarRequestScope,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.public_published_queries import get_published_price_bar_series
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationAuthorityFence,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.published_price_source import PublishedPriceSourceFact
from apps.data_center.application.sync_market_use_cases import SyncPriceUseCase
from apps.data_center.domain.control_plane import CanonicalPublication
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import DataCapability, PriceAdjustment
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    PublicationPolicyRepositoryProtocol,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.publication_lanes import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncClock,
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.candidate_raw_audit_manifest_repository import (
    DjangoCandidateRawAuditManifestRepository,
)
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import PublicationPolicyRepository
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel
from apps.data_center.infrastructure.m1_reference_price_publication_audit import (
    M1ReferencePricePublicationAuditWriter,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.provider_state_repositories import (
    ProviderConfigRepository,
    RawAuditRepository,
)
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from apps.data_center.infrastructure.publication_models import CanonicalPublicationPointerModel
from apps.data_center.infrastructure.published_price_source_repository import (
    DjangoPublishedPriceSourceRepository,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from core.exceptions import DataValidationError
from tests.component.data_center.test_execution_quote_activation_workflow import (
    _TestAuthorityFence,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database


def test_m1_reference_price_builder_accepts_only_exact_lane() -> None:
    """Allow candidate construction only for the fixed M1 price-bar lane."""

    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=CurrentPublicationDataset(
            dataset_key="equity.price.bar",
            fact_table="data_center_price_bar",
            created_by="tests.m1_reference_price",
        ),
        candidate_repository=cast(CurrentPublicationCandidateRepositoryProtocol, object()),
        publication_repository=cast(CanonicalPublicationRepositoryPort, object()),
        policy_repository=cast(PublicationPolicyRepositoryProtocol, object()),
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )

    assert rebuilder.publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY

    with pytest.raises(ValueError):
        CurrentPublicationRebuildUseCase(
            dataset=CurrentPublicationDataset(
                dataset_key="equity.quote.snapshot",
                fact_table="data_center_quote_snapshot",
                created_by="tests.m1_reference_price",
            ),
            candidate_repository=cast(CurrentPublicationCandidateRepositoryProtocol, object()),
            publication_repository=cast(CanonicalPublicationRepositoryPort, object()),
            policy_repository=cast(PublicationPolicyRepositoryProtocol, object()),
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )


def test_m1_activation_group_accepts_only_exact_lane() -> None:
    """Allow the fixed M1 price scope through the existing group activation UOW."""

    candidate = PublicationActivationGroupCandidate(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        candidate_publication_id=str(uuid4()),
        candidate_publication_hash="a" * 64,
    )
    request = PublicationActivationGroupRequest(
        activation_id=str(uuid4()),
        candidates=(candidate,),
    )

    assert request.candidates == (candidate,)
    assert not request.is_execution_quote_activation

    with pytest.raises(PublicationActivationError):
        PublicationActivationGroupRequest(
            activation_id=str(uuid4()),
            candidates=(
                PublicationActivationGroupCandidate(
                    dataset_key="equity.price.bar",
                    publication_key="m1-arbitrary",
                    candidate_publication_id=str(uuid4()),
                    candidate_publication_hash="b" * 64,
                ),
            ),
        )


def test_m1_composition_passes_same_environment_to_preflight_and_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the explicit environment consistent across both authority gates."""

    environments: list[str] = []
    now = timezone.now()
    context = SystemAuditReaderContext._from_authority(
        authority_source_id="fixture:m1-authority",
        authority_source_version="1",
        actor_id="django-user:7",
        user_id=7,
        tenant_id="fixture-tenant",
        owner_id="fixture-owner",
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=now - timedelta(minutes=1),
        authority_valid_until=now + timedelta(hours=1),
    )

    def preflight(*, environment: str, using: str, as_of: datetime) -> SystemAuditReaderContext:
        assert using == "default"
        assert as_of == now
        environments.append(environment)
        return context

    def capture(
        *,
        environment: str,
        using: str,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> object:
        assert using == "default"
        assert as_of == now
        assert preflight_context is context
        environments.append(environment)
        raise RuntimeError("capture observed")

    monkeypatch.setattr(
        m1_composition,
        "get_data_reliability_audit_writers",
        lambda **_kwargs: (
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            SimpleNamespace(database_alias="default"),
        ),
    )
    monkeypatch.setattr(
        m1_composition,
        "make_system_audited_sync_price_use_case",
        lambda **_kwargs: cast(SyncPriceUseCase, object()),
    )
    monkeypatch.setattr(
        m1_composition,
        "preflight_data_reliability_audit_runtime",
        preflight,
    )
    monkeypatch.setattr(
        m1_composition,
        "capture_account_authority_for_environment",
        capture,
    )
    use_case = m1_composition.build_m1_reference_price_publication_use_case(
        provider_repository=cast(ProviderConfigRepositoryProtocol, object()),
        provider_registry=cast(ProviderRegistryProtocol, object()),
        environment="development",
    )

    assert use_case._authority_preflight(as_of=now) is context
    with pytest.raises(RuntimeError, match="capture observed"):
        use_case._authority_capture(as_of=now, preflight_context=context)

    assert environments == ["development", "development"]


def test_m1_command_rejects_noncanonical_asset_and_date_scope() -> None:
    """Reject aliases and datetime values before any sync or persistence call."""

    target_date = date(2026, 10, 27)
    invalid_scopes = (
        ("000001.sz", target_date),
        ("000001", target_date),
        ("000001.SZ", timezone.now()),
    )
    for asset_code, trade_date in invalid_scopes:
        with pytest.raises(DataValidationError):
            M1ReferencePricePublicationCommand(
                provider_id=1,
                asset_code=asset_code,
                target_trade_date=trade_date,
            )


def _build_m1_test_use_case(
    *,
    fail_quality: bool = False,
) -> tuple[
    M1ReferencePricePublicationUseCase,
    _M1ExactPriceProvider,
    int,
    _RecordingM1GroupActivation,
]:
    """Build the formal M1 application path with real PostgreSQL repositories."""

    provider_row = ProviderConfigModel._default_manager.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    if provider_row.pk is None:
        raise AssertionError("test provider identity was not created")
    provider_id = int(provider_row.pk)
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

    providers = ProviderConfigRepository()
    providers._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    source = _M1ExactPriceProvider(provider_id)
    registry = ProviderRegistry()
    registry.register(source, priority=1, provider_id=provider_id, source_type="tushare")
    facts = PriceBarRepository()
    raw_audits = RawAuditRepository()
    raw_payloads = RawLandingRepository()
    identities = SyncExecutionIdentityRepository()
    coordinator = DjangoSystemAuditEventOutboxCoordinator()
    scope_provider = _M1AuditScopeProvider()
    fetch_writer = AppendDataFetchAuditObservationUseCase(coordinator, scope_provider)
    publication_writer = AppendDataPublicationAuditObservationUseCase(
        coordinator,
        scope_provider,
    )
    sync_quality_writer = AppendDataQualityAuditObservationUseCase(coordinator, scope_provider)
    sync_uow = DjangoDataCenterSyncUnitOfWork(
        (providers, facts, raw_audits, raw_payloads, identities),
        fetch_writer,
        additional_audit_writers=(publication_writer, sync_quality_writer),
        using="default",
    )
    clock = DjangoDataCenterSyncClock()
    exact_sync = SyncPriceUseCase(
        providers,
        registry,
        facts,
        raw_audits,
        publication_publisher=None,
        sync_identity_issuer=DjangoSyncExecutionIdentityIssuer(identities),
        sync_unit_of_work=sync_uow,
        data_fetch_audit_writer=fetch_writer,
        data_publication_audit_writer=publication_writer,
        clock=clock,
        provider_response_payload_retainer=RetainProviderResponsePayloadUseCase(raw_payloads),
    )

    publication_repository = CanonicalPublicationRepository()
    dataset = CurrentPublicationDataset(
        dataset_key="equity.price.bar",
        fact_table="data_center_price_bar",
        created_by="tests.m1_reference_price",
    )
    rebuilder = CurrentPublicationRebuildUseCase(
        dataset=dataset,
        candidate_repository=facts,
        publication_repository=publication_repository,
        policy_repository=PublicationPolicyRepository(),
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    staging = CurrentPublicationStagingUseCase(
        rebuilder=rebuilder,
        raw_audit_resolver=DjangoCandidateRawAuditMetadataResolver(),
        repository=DjangoCurrentPublicationStagingRepository(
            publication_repository=publication_repository,
        ),
    )
    activation = _RecordingM1GroupActivation(
        DjangoPublicationActivationGroupRepository(using="default")
    )
    if fail_quality:
        quality_recorder = cast(
            RecordPublicationQualityUseCase,
            _FailingM1QualityRecorder(),
        )
    else:
        quality_recorder = RecordPublicationQualityUseCase(
            publication_reader=publication_repository,
            quality_writer=sync_quality_writer,
            clock=clock,
        )

    def authority_preflight(*, as_of: datetime) -> SystemAuditReaderContext:
        """Return an explicit capability-bearing component-test context."""

        return SystemAuditReaderContext._from_authority(
            authority_source_id="fixture:m1-authority",
            authority_source_version="1",
            actor_id="django-user:7",
            user_id=7,
            tenant_id="fixture-tenant",
            owner_id="fixture-owner",
            authority_content_hash="a" * 64,
            is_authenticated=True,
            is_staff=True,
            role="admin",
            authority_state="active",
            authority_recorded_at=as_of - timedelta(minutes=1),
            authority_valid_until=as_of + timedelta(hours=1),
        )

    def authority_capture(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> _M1AuthorityCapture:
        """Use the same complete-fence port exercised by the execution component tests."""

        return _M1AuthorityCapture(
            database_alias="default",
            authority_fence=_M1AuthorityFence(
                checked_at=as_of,
                tenant_id=preflight_context.tenant_id,
                owner_id=preflight_context.owner_id,
            ),
            authority_proof="fixture-authority-proof",
        )

    def read_pointer(dataset_key: str, publication_key: str) -> CurrentPublicationPointerSnapshot:
        """Read the real M1 pointer row before stage and compare-and-swap."""

        if (
            dataset_key != "equity.price.bar"
            or publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        ):
            raise AssertionError("M1 test pointer reader received another scope")
        pointer = CanonicalPublicationPointerModel._default_manager.filter(
            dataset_key=dataset_key,
            publication_key=publication_key,
        ).first()
        if pointer is None:
            return CurrentPublicationPointerSnapshot(None, None)
        if pointer.publication_id is None:
            if pointer.publication_hash or pointer.activation_id:
                raise AssertionError("test pointer has an invalid empty identity")
            return CurrentPublicationPointerSnapshot(None, None)
        return CurrentPublicationPointerSnapshot(
            str(pointer.publication_id),
            pointer.publication_hash,
        )

    def audit_writer_factory() -> PublicationActivationGroupAuditWriter:
        """Use the real manifest/outbox writer and the M1 quality wrapper."""

        return M1ReferencePricePublicationAuditWriter(
            delegate=DjangoPublicationActivationAuditWriter(coordinator),
            quality_recorder=quality_recorder,
        )

    use_case = M1ReferencePricePublicationUseCase(
        price_sync=exact_sync,
        provider_repository=providers,
        staging=staging,
        activate_group=activation,
        audit_writer_factory=audit_writer_factory,
        authority_preflight=authority_preflight,
        authority_capture=authority_capture,
        current_pointer_reader=read_pointer,
        clock=clock,
    )
    return use_case, source, provider_id, activation


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_exact_daily_capture_stages_and_activates_m1_publication(
    monkeypatch: pytest.MonkeyPatch,
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    """Run exact sync through real stage/group repos and the member-scoped M1 reader."""

    use_case, source, provider_id, activation = _build_m1_test_use_case()
    target_date = date(2026, 10, 27)
    outcome = use_case.execute(
        M1ReferencePricePublicationCommand(
            provider_id=provider_id,
            asset_code="000001.SZ",
            target_trade_date=target_date,
        )
    )

    assert source.calls == [("000001.SZ", target_date)]
    assert outcome.sync_result.status == "success"
    assert outcome.sync_result.stored_count == 1
    assert outcome.sync_result.raw_audit_reference is not None
    assert outcome.publication.publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert outcome.publication.member_count == 1
    assert outcome.publication.selected_source == "tushare"
    raw_audit = RawAuditModel._default_manager.get(
        pk=int(outcome.sync_result.raw_audit_reference.raw_audit_id)
    )
    assert raw_audit.provider_name == "Tushare Pro"
    assert raw_audit.extra["source_type"] == "tushare"
    manifest = DjangoCandidateRawAuditManifestRepository().validate(
        outcome.publication.publication_id
    )
    assert manifest.raw_audit_count == 1
    assert (
        manifest.raw_audits[0].raw_audit_id == outcome.sync_result.raw_audit_reference.raw_audit_id
    )
    assert (
        CanonicalPublicationRepository().get_current(
            "equity.price.bar", M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        )
        == outcome.publication
    )
    assert CanonicalPublicationRepository().get_current("equity.price.bar", "current") is None
    manifest_event = SystemAuditEventModel._default_manager.get(
        event_type="data.publication.published",
        publication_id=outcome.publication.publication_id,
    )
    assert manifest_event.detail_schema == "data.publication.published.v1"
    assert manifest_event.detail["raw_audit_manifest"]["manifest_id"] == manifest.manifest_id
    assert SystemAuditOutboxModel._default_manager.filter(event_id=manifest_event.event_id).exists()
    public_result = get_published_price_bar_series(
        "000001.SZ",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        start=target_date,
        end=target_date,
        knowledge_cutoff=timezone.now(),
    )
    rows = cast(list[dict[str, object]], public_result["rows"])
    assert public_result["publication_key"] == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert public_result["must_not_use_for_decision"] is False
    assert public_result["freshness_status"] == "fresh"
    assert len(rows) == 1
    assert rows[0]["asset_code"] == "000001.SZ"
    assert rows[0]["timestamp"] == target_date.isoformat()
    assert Decimal(str(rows[0]["close"])) == Decimal("11.47")

    from apps.data_center.application.public_published_queries import (
        get_published_price_bar_source,
    )

    original_read = DjangoPublishedPriceSourceRepository.read_facts
    read_modes: list[tuple[str, str]] = []

    def inspect_read_boundary(
        repository: DjangoPublishedPriceSourceRepository,
        *,
        asset_code: str,
        trade_date: date,
        fact_pks: tuple[str, ...],
    ) -> tuple[PublishedPriceSourceFact, ...]:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                read_only = cursor.fetchone()[0]
                cursor.execute("SHOW transaction_isolation")
                isolation = cursor.fetchone()[0]
            read_modes.append((read_only, isolation))
        return original_read(
            repository, asset_code=asset_code, trade_date=trade_date, fact_pks=fact_pks
        )

    monkeypatch.setattr(DjangoPublishedPriceSourceRepository, "read_facts", inspect_read_boundary)
    assert not connection.in_atomic_block
    if connection.vendor == "postgresql":
        record_testsuite_property(
            "price_source_test_database", assert_native_postgres_test_database()
        )
    cutoff = timezone.now()
    with CaptureQueriesContext(connection) as source_queries:
        source_result = get_published_price_bar_source(
            "000001.SZ",
            trade_date=target_date,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=cutoff,
        )
    if connection.vendor == "postgresql":
        assert read_modes == [("on", "repeatable read")]
        record_testsuite_property("price_source_transaction_read_only", read_modes[0][0])
        record_testsuite_property("price_source_transaction_isolation", read_modes[0][1])
    for query in source_queries:
        sql = query["sql"].strip().upper()
        assert "FOR UPDATE" not in sql
        assert not sql.startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))
    assert source_result.blocked_reason == ""
    evidence = source_result.evidence
    assert evidence is not None
    assert evidence.publication_id == outcome.publication.publication_id
    assert evidence.publication_hash == outcome.publication.publication_hash
    assert evidence.publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert evidence.asset_code == "000001.SZ"
    assert evidence.trade_date == target_date
    assert evidence.values.close == Decimal("11.4700")
    assert type(evidence.values.close) is Decimal
    assert evidence.volume_unit == "shares"
    assert evidence.amount_unit == "CNY"
    assert evidence.availability_basis == "local_response_body_completion"
    assert evidence.observed_at <= evidence.available_at <= cutoff
    assert evidence.source_published_at is None
    assert evidence.fact_recorded_at <= cutoff
    assert evidence.raw_audit_reference == manifest.raw_audits[0]
    assert evidence.raw_payload_reference.payload_hash == raw_audit.response_payload_hash
    assert evidence.raw_payload_reference.response_completed_at == evidence.available_at
    assert source.calls == [("000001.SZ", target_date)]

    assert len(activation.calls) == 1
    replay = activation.calls[0]
    event_count = SystemAuditEventModel._default_manager.count()
    outbox_count = SystemAuditOutboxModel._default_manager.count()
    replayed = activation.execute(
        replay.request,
        audit_writer=replay.audit_writer,
        authority_fence=replay.authority_fence,
        authority_proof=replay.authority_proof,
    )
    assert replayed == (outcome.publication,)
    assert SystemAuditEventModel._default_manager.count() == event_count
    assert SystemAuditOutboxModel._default_manager.count() == outbox_count
    assert (
        CanonicalPublicationRepository().get_current(
            "equity.price.bar", M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        )
        == outcome.publication
    )


@pytest.mark.django_db(
    transaction=True,
    available_apps=["apps.data_center", "apps.audit"],
)
def test_m1_quality_failure_rolls_back_pointer_and_required_manifest_event() -> None:
    """A failed M1 quality audit rolls back pointer and publication audit writes."""

    use_case, _source, provider_id, _activation = _build_m1_test_use_case(fail_quality=True)
    with pytest.raises(DataValidationError):
        use_case.execute(
            M1ReferencePricePublicationCommand(
                provider_id=provider_id,
                asset_code="000001.SZ",
                target_trade_date=date(2026, 10, 27),
            )
        )

    pointer = CanonicalPublicationPointerModel._default_manager.get(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    assert pointer.publication_id is None
    assert not SystemAuditEventModel._default_manager.filter(
        event_type="data.publication.published"
    ).exists()
    assert SystemAuditOutboxModel._default_manager.count() == 1


class _M1AuditScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        del as_of
        return AuditScopeRef("fixture-tenant", "fixture-owner")


class _M1AuthorityFence:
    database_alias = "default"

    def __init__(self, *, checked_at: datetime, tenant_id: str, owner_id: str) -> None:
        self._delegate = _TestAuthorityFence(
            checked_at=checked_at,
            tenant_id=tenant_id,
            owner_id=owner_id,
        )

    def fence_complete(self, proof: object) -> AbstractContextManager[object]:
        return self._delegate.fence_complete(proof)


@dataclass(frozen=True, slots=True)
class _M1AuthorityCapture:
    database_alias: str
    authority_fence: _M1AuthorityFence
    authority_proof: object


@dataclass(frozen=True, slots=True)
class _RecordedM1Activation:
    request: PublicationActivationGroupRequest
    audit_writer: PublicationActivationGroupAuditWriter
    authority_fence: PublicationActivationAuthorityFence
    authority_proof: object


class _RecordingM1GroupActivation(ActivateCanonicalPublicationGroupUseCase):
    """Capture the exact singleton request for a same-request replay assertion."""

    def __init__(self, repository: DjangoPublicationActivationGroupRepository) -> None:
        super().__init__(repository)
        self.calls: list[_RecordedM1Activation] = []

    def execute(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        self.calls.append(
            _RecordedM1Activation(
                request=request,
                audit_writer=audit_writer,
                authority_fence=authority_fence,
                authority_proof=authority_proof,
            )
        )
        return super().execute(
            request,
            audit_writer=audit_writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )


class _FailingM1QualityRecorder:
    database_alias = "default"

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> None:
        del publication_id, run_id, ingested_run_id, provider_key
        raise ValueError("forced M1 quality failure")


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


class _M1ExactPriceProvider:
    def __init__(self, provider_id: int) -> None:
        self.provider_id = provider_id
        self.calls: list[tuple[str, date]] = []

    def provider_name(self) -> str:
        return "Tushare Pro"

    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.HISTORICAL_PRICE

    def fetch_price_history(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> list[PriceBar]:
        del asset_code, start, end
        raise AssertionError("M1 exact daily sync must not use historical fallback")

    def fetch_price_bar_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceBarResponse:
        self.calls.append((asset_code, target_trade_date))
        completed_at = timezone.now()
        request_scope = ExactPriceBarRequestScope(
            provider_id=self.provider_id,
            provider_name="Tushare Pro",
            dataset_key="equity.price.bar",
            api_name="daily",
            asset_code=asset_code,
            trade_date=target_trade_date,
        )
        body = json.dumps(
            {
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
                    "items": [
                        [
                            asset_code,
                            target_trade_date.strftime("%Y%m%d"),
                            11.4,
                            11.5,
                            11.3,
                            11.47,
                            200,
                            2100,
                        ]
                    ],
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        capture = ProviderResponseCapture(
            body=body,
            payload=parse_provider_response_json(body),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=completed_at,
            status_code=200,
            content_type="application/json",
            transport=ProviderResponseTransport.DIRECT,
        )
        return CapturedPriceBarResponse(
            request_scope=request_scope,
            bar=PriceBar(
                asset_code=asset_code,
                bar_date=target_trade_date,
                open=11.4,
                high=11.5,
                low=11.3,
                close=11.47,
                volume=20_000.0,
                amount=2_100_000.0,
                freq="1d",
                adjustment=PriceAdjustment.NONE,
                source="tushare",
                fetched_at=completed_at,
            ),
            capture=capture,
        )
