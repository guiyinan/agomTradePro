"""SQLite proof that an audited macro sync commits or rolls back as one unit."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.audit.application.data_decision_read_audit import (
    AppendDataDecisionReadAuditObservationUseCase,
)
from apps.audit.application.data_failover_audit import (
    AppendDataFailoverAuditObservationUseCase,
)
from apps.audit.application.data_fetch_audit import (
    AppendDataFetchAuditObservationUseCase,
    DataFetchAuditObservation,
)
from apps.audit.application.data_freshness_audit import (
    AppendDataFreshnessAuditObservationUseCase,
)
from apps.audit.application.data_provider_health_audit import (
    AppendDataProviderHealthAuditObservationUseCase,
)
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
)
from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
)
from apps.audit.application.data_repair_audit import (
    AppendDataRepairAuditObservationUseCase,
    DataRepairAuditObservation,
    RepairPublicationEvidence,
    RepairSectionEvidence,
)
from apps.audit.application.data_validation_audit import (
    AppendDataValidationRejectedObservationUseCase,
)
from apps.audit.application.system_audit_query import (
    ListCorrelatedSystemAuditEventsUseCase,
    SystemAuditReaderContext,
)
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_repository import DjangoSystemAuditEventRepository
from apps.data_center.application.data_chain_replay import (
    DataChainReplayCommand,
    ReplayDataChainUseCase,
)
from apps.data_center.application.decision_read_audit import (
    RecordPublicationDecisionReadCommand,
    RecordPublicationDecisionReadUseCase,
)
from apps.data_center.application.dtos import MacroFailoverDecision, SyncMacroRequest
from apps.data_center.application.macro_publication import PublishMacroBatchUseCase
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.repair_run_replay import (
    RepairRunReplayCommand,
    ReplayRepairRunUseCase,
)
from apps.data_center.application.sync_use_cases import SyncMacroUseCase
from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataCapability
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoRepairRunIdentityUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.catalog_repositories import (
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.data_chain_replay_evidence import (
    DjangoReplayFactEvidenceReader,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    RawAuditModel,
    SyncExecutionIdentityModel,
)
from apps.data_center.infrastructure.macro_fact_storage_repository import MacroFactRepository
from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
    ProviderConfigModel,
)
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
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    ProviderConfigModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    DatasetPublicationPolicyModel,
    MacroFactModel,
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
        return capability is DataCapability.MACRO

    def fetch_macro_series(
        self,
        indicator_code: str,
        start: date,
        end: date,
    ) -> list[MacroFact]:
        assert indicator_code == "CN_CPI"
        assert start <= date(2026, 8, 1) <= end
        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=date(2026, 8, 1),
                value=2.1,
                unit="%",
                source="tushare",
                published_at=date(2026, 8, 3),
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


def _seed_contracts() -> tuple[int, int]:
    provider = ProviderConfigModel._default_manager.create(
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    verifier = ProviderConfigModel._default_manager.create(
        name="provider-verifier",
        source_type="akshare",
        is_active=True,
        priority=2,
        extra_config={},
    )
    IndicatorCatalogModel._default_manager.create(
        code="CN_CPI",
        name_cn="CPI",
        name_en="CPI",
        default_unit="%",
        default_period_type="M",
        category="prices",
    )
    IndicatorUnitRuleModel._default_manager.create(
        indicator_code="CN_CPI",
        source_type="tushare",
        dimension_key="rate",
        original_unit="%",
        storage_unit="%",
        display_unit="%",
        multiplier_to_storage=1,
        is_active=True,
        priority=1,
    )
    DatasetPublicationPolicyModel._default_manager.create(
        dataset_key="macro.fact",
        contract_version="1.0",
        schema_version="1.0",
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=["source", "observed_at", "published_at", "payload_hash"],
        retention_days=3650,
        active=True,
    )
    assert provider.pk is not None
    assert verifier.pk is not None
    return int(provider.pk), int(verifier.pk)


def _build_use_case(
    audit_writer: AppendDataFetchAuditObservationUseCase | _FailAfterAuditWriter,
    *,
    pre_degrade_provider: bool = False,
) -> tuple[SyncMacroUseCase, int, int]:
    provider_id, verifier_id = _seed_contracts()
    provider_repo = ProviderConfigRepository()
    provider_repo._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    registry = ProviderRegistry()
    registry.register(
        _Provider(),
        priority=1,
        provider_id=provider_id,
        source_type="tushare",
    )
    if pre_degrade_provider:
        registry.record_failure("provider-main", DataCapability.MACRO)
    fact_repo = MacroFactRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    publication_audit_writer = _canonical_publication_writer()
    validation_audit_writer = _canonical_validation_writer()
    failover_audit_writer = _canonical_failover_writer()
    provider_health_audit_writer = _canonical_provider_health_writer()
    quality_audit_writer = _canonical_quality_writer()
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repo,
        quality_writer=quality_audit_writer,
        clock=_Clock(),
    )
    publisher = PublishMacroBatchUseCase(
        fact_repository=fact_repo,
        publication_repository=publication_repo,
        policy_repository=policy_repo,
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
        additional_audit_writers=(
            publication_audit_writer,
            validation_audit_writer,
            failover_audit_writer,
            provider_health_audit_writer,
            quality_audit_writer,
        ),
    )
    return (
        SyncMacroUseCase(
            provider_repo=provider_repo,
            provider_registry=registry,
            fact_repo=fact_repo,
            catalog_repo=IndicatorCatalogRepository(),
            unit_rule_repo=IndicatorUnitRuleRepository(),
            raw_audit_repo=raw_audit_repo,
            publication_publisher=publisher,
            sync_identity_issuer=DjangoSyncExecutionIdentityIssuer(identity_repo),
            sync_unit_of_work=unit_of_work,
            data_fetch_audit_writer=audit_writer,
            data_publication_audit_writer=publication_audit_writer,
            publication_quality_recorder=quality_recorder,
            data_validation_audit_writer=validation_audit_writer,
            data_failover_audit_writer=failover_audit_writer,
            data_provider_health_audit_writer=provider_health_audit_writer,
            clock=_Clock(),
        ),
        provider_id,
        verifier_id,
    )


def _request(
    provider_id: int,
) -> SyncMacroRequest:
    return SyncMacroRequest(
        provider_id=provider_id,
        indicator_code="CN_CPI",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
    )


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


def _canonical_validation_writer() -> AppendDataValidationRejectedObservationUseCase:
    return AppendDataValidationRejectedObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_failover_writer() -> AppendDataFailoverAuditObservationUseCase:
    return AppendDataFailoverAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_decision_read_writer() -> AppendDataDecisionReadAuditObservationUseCase:
    return AppendDataDecisionReadAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_provider_health_writer() -> AppendDataProviderHealthAuditObservationUseCase:
    return AppendDataProviderHealthAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_freshness_writer() -> AppendDataFreshnessAuditObservationUseCase:
    return AppendDataFreshnessAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_quality_writer() -> AppendDataQualityAuditObservationUseCase:
    return AppendDataQualityAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _canonical_repair_writer() -> AppendDataRepairAuditObservationUseCase:
    return AppendDataRepairAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _reader() -> SystemAuditReaderContext:
    return SystemAuditReaderContext._from_authority(
        authority_source_id="authority:test",
        authority_source_version="v1",
        actor_id="django-user:7",
        user_id=7,
        tenant_id=SCOPE.tenant_id,
        owner_id=SCOPE.owner_id,
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=NOW - timedelta(minutes=1),
        authority_valid_until=NOW + timedelta(hours=1),
    )


def test_success_commits_correlated_fact_evidence_publication_event_and_outbox() -> None:
    use_case, provider_id, verifier_id = _build_use_case(
        _canonical_writer(),
        pre_degrade_provider=True,
    )
    failover_decision = MacroFailoverDecision(
        from_provider="provider-primary",
        to_provider="provider-main",
        verification_provider="provider-verifier",
        tolerance=0.01,
        observed_deviation=0.005,
        reason_code="primary_unavailable_fallback_verified",
    )

    prepared = use_case.prepare(_request(provider_id))
    verification = dataclasses.replace(
        prepared,
        config=dataclasses.replace(
            prepared.config,
            name="provider-verifier",
            source_type="akshare",
            id=verifier_id,
        ),
        provider_name="provider-verifier",
    )
    result = use_case.commit(
        prepared,
        failover_decision=failover_decision,
        verification=verification,
    )

    assert result.status == "success"
    assert result.publication_id is not None
    RecordPublicationDecisionReadUseCase(
        _canonical_decision_read_writer(),
        _Clock(),
        freshness_writer=_canonical_freshness_writer(),
    ).execute(
        RecordPublicationDecisionReadCommand(
            sync_result=result,
            dataset_key="macro.fact",
            publication_key="CN_CPI",
            decision_key="decision-reliability-macro:CN_CPI",
            freshness_status="fresh",
            must_not_use_for_decision=False,
            blocked_reason=None,
        )
    )
    replay = ReplayDataChainUseCase(
        correlation_query=ListCorrelatedSystemAuditEventsUseCase(
            DjangoSystemAuditEventRepository()
        ),
        raw_audit_reader=RawAuditRepository(),
        publication_reader=CanonicalPublicationRepository(),
        fact_evidence_reader=DjangoReplayFactEvidenceReader(),
    ).execute(
        DataChainReplayCommand(
            run_id=None,
            publication_id=result.publication_id,
            as_of=NOW,
            reader=_reader(),
        )
    )
    identity = SyncExecutionIdentityModel._default_manager.get()
    fact = MacroFactModel._default_manager.get()
    raw_audit = RawAuditModel._default_manager.get(provider_name="provider-main")
    verifier_audit = RawAuditModel._default_manager.get(provider_name="provider-verifier")
    publication = CanonicalPublicationModel._default_manager.get()
    assert result.publication_version is not None
    assert result.publication_hash is not None
    repair_identity_repository = SyncExecutionIdentityRepository()
    with DjangoRepairRunIdentityUnitOfWork(repair_identity_repository).atomic():
        repair_identity = DjangoSyncExecutionIdentityIssuer(repair_identity_repository).issue(
            dataset_key="decision.reliability.repair",
            provider_name="data-center-repair",
        )
    _canonical_repair_writer().write(
        DataRepairAuditObservation(
            identity=repair_identity,
            target_date=date(2026, 8, 27),
            sections=(
                RepairSectionEvidence(
                    section_key="macro",
                    status="ready",
                    must_not_use_for_decision=False,
                    remaining_blocker_count=0,
                ),
            ),
            publications=(
                RepairPublicationEvidence(
                    publication_id=result.publication_id,
                    publication_version=result.publication_version,
                    publication_hash=result.publication_hash,
                    dataset_key="macro.fact",
                ),
            ),
            outcome=AuditOutcome.SUCCESS,
            occurred_at=NOW,
            recorded_at=NOW,
        )
    )
    repair_replay = ReplayRepairRunUseCase(
        correlation_query=ListCorrelatedSystemAuditEventsUseCase(
            DjangoSystemAuditEventRepository()
        ),
        identity_reader=repair_identity_repository,
        publication_replay=ReplayDataChainUseCase(
            correlation_query=ListCorrelatedSystemAuditEventsUseCase(
                DjangoSystemAuditEventRepository()
            ),
            raw_audit_reader=RawAuditRepository(),
            publication_reader=CanonicalPublicationRepository(),
            fact_evidence_reader=DjangoReplayFactEvidenceReader(),
        ),
    ).execute(
        RepairRunReplayCommand(
            run_id=repair_identity.run_id,
            as_of=NOW,
            reader=_reader(),
        )
    )
    event = SystemAuditEventModel._default_manager.get(
        event_type="data.fetch.completed",
        provider_key="provider-main",
    )
    verifier_event = SystemAuditEventModel._default_manager.get(
        event_type="data.fetch.completed",
        provider_key="provider-verifier",
    )
    publication_event = SystemAuditEventModel._default_manager.get(
        event_type="data.publication.published"
    )
    failover_started_event = SystemAuditEventModel._default_manager.get(
        event_type="data.failover.started"
    )
    failover_event = SystemAuditEventModel._default_manager.get(
        event_type="data.failover.succeeded"
    )
    decision_read_event = SystemAuditEventModel._default_manager.get(
        event_type="data.decision_read.recovered"
    )
    freshness_event = SystemAuditEventModel._default_manager.get(
        event_type="data.freshness.changed"
    )
    provider_recovered_event = SystemAuditEventModel._default_manager.get(
        event_type="data.provider.recovered"
    )
    repair_event = SystemAuditEventModel._default_manager.get(event_type="data.repair.completed")
    outbox = SystemAuditOutboxModel._default_manager.get(event_id=event.event_id)
    assert str(fact.ingested_run_id) == str(identity.ingested_run_id)
    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert str(verifier_audit.run_id) == str(identity.run_id)
    assert str(verifier_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert str(publication.run_id) == str(identity.run_id)
    assert event.event_type == "data.fetch.completed"
    assert event.correlations["run_id"] == str(identity.run_id)
    assert event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert event.resource_id == str(raw_audit.pk)
    assert event.evidence_refs[0]["content_hash"] == raw_audit.content_hash
    assert event.scope_tenant_id == SCOPE.tenant_id
    assert event.scope_owner_id == SCOPE.owner_id
    assert outbox.event_id == event.event_id
    assert outbox.payload_hash == event.content_hash
    assert verifier_event.evidence_refs[0]["artifact_id"] == str(verifier_audit.pk)
    assert publication_event.publication_id == str(publication.publication_id)
    assert publication_event.correlations["run_id"] == str(identity.run_id)
    assert publication_event.evidence_refs[0]["artifact_id"] == str(raw_audit.pk)
    assert failover_started_event.correlations["run_id"] == str(identity.run_id)
    assert failover_started_event.evidence_refs[0]["artifact_id"] == str(raw_audit.pk)
    assert failover_event.correlations["run_id"] == str(identity.run_id)
    assert failover_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert failover_event.evidence_refs[0]["artifact_id"] == str(raw_audit.pk)
    assert failover_event.detail["observed_deviation"] == pytest.approx(0.005)
    assert decision_read_event.publication_id == str(publication.publication_id)
    assert freshness_event.publication_id == str(publication.publication_id)
    assert freshness_event.detail["previous_freshness_status"] == "unknown"
    assert freshness_event.detail["freshness_status"] == "fresh"
    assert freshness_event.evidence_refs[0]["content_hash"] == publication.publication_hash
    assert provider_recovered_event.correlations["run_id"] == str(identity.run_id)
    assert provider_recovered_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert provider_recovered_event.provider_key == "provider-main"
    assert provider_recovered_event.dataset_key == "macro.fact"
    assert provider_recovered_event.evidence_refs[0]["artifact_type"] == (
        "provider_health_snapshot"
    )
    assert replay.resolved_run_id == str(identity.run_id)
    assert replay.ingested_run_id == str(identity.ingested_run_id)
    assert replay.publication_id == str(publication.publication_id)
    assert replay.member_count == 1
    assert repair_event.correlations["run_id"] == repair_identity.run_id
    assert repair_event.correlations["ingested_run_id"] == repair_identity.ingested_run_id
    assert repair_event.evidence_refs[0]["artifact_id"] == repair_identity.identity_hash
    assert repair_event.evidence_refs[1]["artifact_id"] == result.publication_id
    assert repair_replay.resolved_run_id == repair_identity.run_id
    assert repair_replay.identity_hash == repair_identity.identity_hash
    assert repair_replay.publication_ids == (result.publication_id,)
    assert repair_replay.publication_replays[0] == replay
    assert replay.ordered_stage_keys == (
        "data.fetch.completed",
        "data.failover.started",
        "data.failover.succeeded",
        "data.publication.published",
        "data.freshness.changed",
        "data.decision_read.recovered",
    )
    assert SystemAuditEventModel._default_manager.count() == 9
    assert SystemAuditOutboxModel._default_manager.count() == 9
    assert PublicationMemberModel._default_manager.count() == 1
    assert CoverageSnapshotModel._default_manager.count() == 1


def test_failure_after_audit_append_rolls_back_every_transaction_participant() -> None:
    writer = _FailAfterAuditWriter(_canonical_writer())
    use_case, provider_id, _verifier_id = _build_use_case(writer)

    with pytest.raises(RuntimeError, match="failure after canonical audit append"):
        use_case.execute(_request(provider_id))

    assert MacroFactModel._default_manager.count() == 0
    assert SyncExecutionIdentityModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
    provider = ProviderConfigModel._default_manager.get(pk=provider_id)
    assert provider.extra_config == {}


def test_candidate_exhaustion_commits_exact_raw_evidence_and_required_outbox() -> None:
    use_case, _provider_id, _verifier_id = _build_use_case(_canonical_writer())

    use_case.exhaust_failover(
        indicator_code="CN_CPI",
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
        from_provider="provider-main",
        attempted_provider_names=("provider-main", "provider-verifier"),
        tolerance=0.01,
    )

    identity = SyncExecutionIdentityModel._default_manager.get(
        provider_name="macro-provider-candidates"
    )
    raw_audit = RawAuditModel._default_manager.get(provider_name="macro-provider-candidates")
    fetch_event = SystemAuditEventModel._default_manager.get(event_type="data.fetch.failed")
    started_event = SystemAuditEventModel._default_manager.get(event_type="data.failover.started")
    exhausted_event = SystemAuditEventModel._default_manager.get(
        event_type="data.failover.exhausted"
    )

    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert raw_audit.request_params["attempted_provider_names"] == [
        "provider-main",
        "provider-verifier",
    ]
    assert fetch_event.correlations["run_id"] == str(identity.run_id)
    assert exhausted_event.correlations["run_id"] == str(identity.run_id)
    assert exhausted_event.correlations["ingested_run_id"] == str(identity.ingested_run_id)
    assert exhausted_event.write_policy == "required"
    assert exhausted_event.severity == "critical"
    assert exhausted_event.evidence_refs == fetch_event.evidence_refs
    assert exhausted_event.evidence_refs[0]["artifact_id"] == str(raw_audit.pk)
    assert exhausted_event.evidence_refs[0]["content_hash"] == raw_audit.content_hash
    assert started_event.predecessor_hash is None
    assert exhausted_event.predecessor_hash == started_event.content_hash
    assert SystemAuditEventModel._default_manager.count() == 3
    assert SystemAuditOutboxModel._default_manager.count() == 3
