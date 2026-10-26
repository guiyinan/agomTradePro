"""SQLite proof that an audited quote sync commits or rolls back as one unit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from importlib import import_module
from typing import TYPE_CHECKING

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.audit.application.data_fetch_audit import (
    AppendDataFetchAuditObservationUseCase,
    DataFetchAuditObservation,
)
from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
    DataPublicationAuditScopeProvider,
)
from apps.audit.application.data_quality_audit import (
    AppendDataQualityAuditObservationUseCase,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.dtos import SyncQuoteRequest
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import PublishQuoteSnapshotBatchUseCase
from apps.data_center.application.quote_response_capture import (
    CapturedQuoteSnapshotResponse,
    ExactQuoteRequestScope,
)
from apps.data_center.application.sync_use_cases import SyncQuoteUseCase
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
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
    RawPayloadModel,
    SyncExecutionIdentityModel,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, QuoteSnapshotModel
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
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.isolated_schema import isolated_schema

if TYPE_CHECKING:
    from apps.data_center.application.quote_session_capture import CapturedQuoteSessionResponse

pytestmark = pytest.mark.django_db(transaction=True)

_ACCOUNT_GENERATION_MIGRATION = import_module(
    "apps.account.migrations.0065_account_authority_generation"
)
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
TARGET_TRADE_DATE = date(2026, 8, 26)
PROVIDER_SECRET = "provider-secret"
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    ProviderConfigModel,
    DatasetPublicationPolicyModel,
    QuoteSnapshotModel,
    RawPayloadModel,
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
            # --nomigrations still syncs the model table but skips its data migration.
            # Use the production migration initializer so the flush guard observes
            # the real required singleton without repairing or clearing it itself.
            with connection.schema_editor() as schema_editor:
                _ACCOUNT_GENERATION_MIGRATION.seed_generation_row(
                    django_apps,
                    schema_editor,
                )
            yield


class _Provider:
    def provider_name(self) -> str:
        return "provider-main"

    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.REALTIME_QUOTE

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        assert asset_codes == ["000001.SZ"]
        return [
            QuoteSnapshot(
                asset_code=asset_codes[0],
                snapshot_at=NOW,
                fetched_at=NOW,
                current_price=10.5,
                source="tushare",
            )
        ]


class _ExactCaptureProvider:
    def __init__(self, provider_id: int) -> None:
        self._provider_id = provider_id

    def provider_name(self) -> str:
        return "provider-main"

    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.REALTIME_QUOTE

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        raise AssertionError("exact capture must use the captured-response method")

    def fetch_quote_snapshot_with_capture(
        self, asset_code: str, target_trade_date: date
    ) -> CapturedQuoteSnapshotResponse:
        assert asset_code == "000001.SZ"
        assert target_trade_date == TARGET_TRADE_DATE
        body = json.dumps(
            {
                "code": 0,
                "msg": PROVIDER_SECRET,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [[asset_code, target_trade_date.strftime("%Y%m%d"), 10.5]],
                    "has_more": False,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
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
        request_scope = ExactQuoteRequestScope(
            provider_id=self._provider_id,
            provider_name=self.provider_name(),
            dataset_key="equity.quote.snapshot",
            api_name="daily",
            asset_code=asset_code,
            trade_date=target_trade_date,
        )
        source_record_id = (
            f"tushare:daily:{target_trade_date.strftime('%Y%m%d')}:"
            f"{asset_code}:{capture.body_sha256[:16]}"
        )
        quote = QuoteSnapshot(
            asset_code=asset_code,
            snapshot_at=NOW,
            fetched_at=capture.response_completed_at,
            current_price=10.5,
            source="tushare",
            extra={
                "raw_payload_hash": capture.body_sha256,
                "raw_payload_scope": "batch_response_body",
                "response_completed_at": capture.response_completed_at.isoformat(),
                "source_record_id": source_record_id,
            },
        )
        return CapturedQuoteSnapshotResponse(
            request_scope=request_scope,
            quote=quote,
            capture=capture,
            sensitive_values=(PROVIDER_SECRET,),
        )


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _SessionCaptureProvider(_ExactCaptureProvider):
    """Return one actual byte-bound session fixture before the write transaction."""

    def fetch_quote_snapshots_for_session(
        self, asset_codes: list[str], target_trade_date: date
    ) -> list[QuoteSnapshot]:
        raise AssertionError("captured session must not use the legacy row-only path")

    def fetch_quote_session_with_capture(
        self, asset_codes: list[str], target_trade_date: date
    ) -> CapturedQuoteSessionResponse:
        from apps.data_center.application.quote_session_capture import (
            CapturedQuoteSessionResponse,
            QuoteSessionRequestScope,
        )

        assert not connection.in_atomic_block
        assert asset_codes == ["000001.SZ", "600000.SH"]
        assert target_trade_date == TARGET_TRADE_DATE
        body = json.dumps(
            {
                "code": 0,
                "msg": PROVIDER_SECRET,
                "data": {
                    "fields": ["ts_code", "trade_date", "close"],
                    "items": [[code, "20260826", 10.5] for code in asset_codes],
                    "has_more": False,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
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
        quotes = tuple(
            QuoteSnapshot(
                asset_code=code,
                snapshot_at=cn_market_session_close_utc(target_trade_date),
                fetched_at=NOW,
                current_price=10.5,
                source="tushare",
                extra={
                    "raw_payload_hash": capture.body_sha256,
                    "raw_payload_scope": "batch_response_body",
                    "source_record_id": f"tushare:daily:20260826:{code}:{capture.body_sha256[:16]}",
                },
            )
            for code in asset_codes
        )
        return CapturedQuoteSessionResponse(
            request_scope=QuoteSessionRequestScope(
                provider_id=self._provider_id,
                provider_name=self.provider_name(),
                dataset_key="equity.quote.snapshot",
                api_name="daily",
                asset_codes=tuple(asset_codes),
                target_trade_date=target_trade_date,
            ),
            quotes=quotes,
            capture=capture,
            sensitive_values=(PROVIDER_SECRET,),
        )


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


def _seed_contracts() -> int:
    provider = ProviderConfigModel._default_manager.create(
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={},
    )
    DatasetPublicationPolicyModel._default_manager.create(
        dataset_key="equity.quote.snapshot",
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


def _canonical_publication_writer(
    scope_provider: DataPublicationAuditScopeProvider | None = None,
) -> AppendDataPublicationAuditObservationUseCase:
    return AppendDataPublicationAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        scope_provider or _ScopeProvider(),
    )


def _canonical_quality_writer() -> AppendDataQualityAuditObservationUseCase:
    return AppendDataQualityAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )


def _build_use_case(
    audit_writer: AppendDataFetchAuditObservationUseCase | _FailAfterAuditWriter,
    *,
    publication_scope_provider: DataPublicationAuditScopeProvider | None = None,
    exact_capture: bool = False,
    session_capture: bool = False,
) -> tuple[SyncQuoteUseCase, int]:
    provider_id = _seed_contracts()
    provider_repo = ProviderConfigRepository()
    provider_repo._credentials = _EmptyCredentialStore()  # type: ignore[assignment]
    registry = ProviderRegistry()
    registry.register(
        (
            _SessionCaptureProvider(provider_id)
            if session_capture
            else _ExactCaptureProvider(provider_id) if exact_capture else _Provider()
        ),
        priority=1,
        provider_id=provider_id,
        source_type="tushare",
    )
    fact_repo = QuoteSnapshotRepository()
    raw_audit_repo = RawAuditRepository()
    raw_payload_repo = RawLandingRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    publication_audit_writer = _canonical_publication_writer(publication_scope_provider)
    quality_audit_writer = _canonical_quality_writer()
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repo,
        quality_writer=quality_audit_writer,
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
        additional_audit_writers=(publication_audit_writer, quality_audit_writer),
    )
    return (
        SyncQuoteUseCase(
            provider_repo=provider_repo,
            provider_registry=registry,
            fact_repo=fact_repo,
            raw_audit_repo=raw_audit_repo,
            publication_publisher=(
                None
                if session_capture
                else PublishQuoteSnapshotBatchUseCase(
                    fact_repository=fact_repo,
                    publication_repository=publication_repo,
                    policy_repository=policy_repo,
                )
            ),
            sync_identity_issuer=DjangoSyncExecutionIdentityIssuer(identity_repo),
            sync_unit_of_work=unit_of_work,
            data_fetch_audit_writer=audit_writer,
            data_publication_audit_writer=publication_audit_writer,
            publication_quality_recorder=None if session_capture else quality_recorder,
            clock=_Clock(),
            provider_response_payload_retainer=(
                RetainProviderResponsePayloadUseCase(raw_payload_repo)
                if exact_capture or session_capture
                else None
            ),
        ),
        provider_id,
    )


def _request(provider_id: int) -> SyncQuoteRequest:
    return SyncQuoteRequest(
        provider_id=provider_id,
        asset_codes=["000001.SZ"],
    )


def _exact_request(provider_id: int) -> SyncQuoteRequest:
    return SyncQuoteRequest(
        provider_id=provider_id,
        asset_codes=["000001.SZ"],
        require_exact_asset_codes=True,
        target_trade_date=TARGET_TRADE_DATE,
    )


def test_success_commits_correlated_fact_evidence_publication_events_and_outboxes() -> None:
    use_case, provider_id = _build_use_case(_canonical_writer())

    result = use_case.execute(_request(provider_id))

    assert result.status == "success"
    identity = SyncExecutionIdentityModel._default_manager.get()
    fact = QuoteSnapshotModel._default_manager.get()
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


def test_exact_capture_commits_raw_payload_with_identity_fact_audit_and_publication() -> None:
    use_case, provider_id = _build_use_case(_canonical_writer(), exact_capture=True)

    result = use_case.execute(_exact_request(provider_id))

    assert result.status == "success"
    assert result.run_id is not None
    identity = SyncExecutionIdentityModel._default_manager.get()
    raw_payload = RawPayloadModel._default_manager.get()
    fact = QuoteSnapshotModel._default_manager.get()
    raw_audit = RawAuditModel._default_manager.get()
    publication = CanonicalPublicationModel._default_manager.get()
    assert str(raw_payload.run_id) == str(identity.run_id) == result.run_id
    assert raw_payload.dataset_key == "equity.quote.snapshot"
    assert raw_payload.provider_name == "provider-main"
    assert raw_payload.redacted is True
    assert raw_payload.payload["response_body_sha256"] == fact.raw_payload_hash
    assert raw_payload.payload["original_body_retained"] is False
    retained_response = raw_payload.payload["retained_response_json"]
    assert PROVIDER_SECRET not in retained_response
    assert "[REDACTED]" in retained_response
    assert raw_payload.request_params["params"] == {
        "ts_code": "000001.SZ",
        "trade_date": "20260826",
    }
    payload_reference = fact.extra["provider_response_payload_reference"]
    assert payload_reference["payload_hash"] == raw_payload.payload_hash
    assert payload_reference["run_id"] == str(identity.run_id)
    assert payload_reference["body_sha256"] == raw_payload.payload["response_body_sha256"]
    assert fact.source_record_id.endswith(raw_payload.payload["response_body_sha256"][:16])
    assert str(fact.ingested_run_id) == str(identity.ingested_run_id)
    assert str(raw_audit.run_id) == str(identity.run_id)
    assert str(raw_audit.ingested_run_id) == str(identity.ingested_run_id)
    assert raw_audit.response_payload_hash == raw_payload.payload_hash
    assert str(publication.run_id) == str(identity.run_id)
    assert result.raw_audit_reference is not None
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2
    assert PublicationMemberModel._default_manager.count() == 1
    assert CoverageSnapshotModel._default_manager.count() == 1


def test_full_session_keeps_one_payload_and_two_independent_canonical_fetch_events() -> None:
    """Two real SQL commits share the capture without colliding in the audit outbox."""

    use_case, provider_id = _build_use_case(_canonical_writer(), session_capture=True)
    prepared = use_case.prepare_session(
        provider_id=provider_id,
        asset_codes=("000001.SZ", "600000.SH"),
        target_trade_date=TARGET_TRADE_DATE,
    )
    assert QuoteSnapshotModel._default_manager.count() == 0
    raw_payload = RawPayloadModel._default_manager.get()
    origin_run = str(raw_payload.run_id)
    assert PROVIDER_SECRET not in json.dumps(raw_payload.payload)
    assert SyncExecutionIdentityModel._default_manager.count() == 1

    results = [
        use_case.execute_prefetched_session_batch(
            SyncQuoteRequest(provider_id, [code], True, TARGET_TRADE_DATE), prepared
        )
        for code in ("000001.SZ", "600000.SH")
    ]

    assert all(result.status == "success" for result in results)
    child_runs = {result.run_id for result in results}
    assert len(child_runs) == 2 and origin_run not in child_runs
    assert RawPayloadModel._default_manager.count() == 1
    assert SyncExecutionIdentityModel._default_manager.count() == 3
    assert QuoteSnapshotModel._default_manager.count() == 2
    audits = list(RawAuditModel._default_manager.order_by("pk"))
    assert len(audits) == 2
    for audit in audits:
        assert str(audit.run_id) in child_runs
        assert audit.response_payload_hash == raw_payload.payload_hash
        binding = audit.extra["quote_session_capture"]
        assert binding["origin"]["run_id"] == origin_run
        fact = QuoteSnapshotModel._default_manager.get(ingested_run_id=audit.ingested_run_id)
        assert fact.extra["quote_session_capture"] == binding
    events = list(SystemAuditEventModel._default_manager.filter(event_type="data.fetch.completed"))
    assert len(events) == 2
    assert {event.correlations["run_id"] for event in events} == child_runs
    assert {event.resource_id for event in events} == {str(audit.pk) for audit in audits}
    assert SystemAuditOutboxModel._default_manager.count() == 2
    assert CanonicalPublicationModel._default_manager.count() == 0


def test_full_session_chunk_failure_rolls_back_only_that_chunk_and_preserves_capture() -> None:
    """A failed canonical audit cannot leave facts, child identity or an outbox."""

    use_case, provider_id = _build_use_case(
        _FailAfterAuditWriter(_canonical_writer()), session_capture=True
    )
    prepared = use_case.prepare_session(
        provider_id=provider_id,
        asset_codes=("000001.SZ", "600000.SH"),
        target_trade_date=TARGET_TRADE_DATE,
    )
    raw_payload = RawPayloadModel._default_manager.get()
    parent_hash = SyncExecutionIdentityModel._default_manager.get().identity_hash
    with pytest.raises(RuntimeError, match="failure after canonical audit append"):
        use_case.execute_prefetched_session_batch(
            SyncQuoteRequest(provider_id, ["000001.SZ"], True, TARGET_TRADE_DATE), prepared
        )
    assert RawPayloadModel._default_manager.get().payload_hash == raw_payload.payload_hash
    assert SyncExecutionIdentityModel._default_manager.get().identity_hash == parent_hash
    assert QuoteSnapshotModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0


class _QuoteUowScopeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, int]] = []

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        self.calls.append(
            (
                connection.in_atomic_block,
                QuoteSnapshotModel._default_manager.count(),
            )
        )
        return SCOPE


def test_publication_scope_provider_runs_inside_quote_uow_after_fact_write() -> None:
    """Characterize the legacy authority read after quote staging has begun."""

    scope_provider = _QuoteUowScopeProvider()
    use_case, provider_id = _build_use_case(
        _canonical_writer(),
        publication_scope_provider=scope_provider,
    )

    result = use_case.execute(_request(provider_id))

    assert result.status == "success"
    assert scope_provider.calls == [(True, 1)]


@pytest.mark.parametrize("exact_capture", [False, True])
def test_failure_after_audit_append_rolls_back_every_transaction_participant(
    exact_capture: bool,
) -> None:
    writer = _FailAfterAuditWriter(_canonical_writer())
    use_case, provider_id = _build_use_case(writer, exact_capture=exact_capture)

    with pytest.raises(RuntimeError, match="failure after canonical audit append"):
        use_case.execute(_exact_request(provider_id) if exact_capture else _request(provider_id))

    assert QuoteSnapshotModel._default_manager.count() == 0
    assert RawPayloadModel._default_manager.count() == 0
    assert SyncExecutionIdentityModel._default_manager.count() == 0
    assert RawAuditModel._default_manager.count() == 0
    assert CanonicalPublicationModel._default_manager.count() == 0
    assert PublicationMemberModel._default_manager.count() == 0
    assert CoverageSnapshotModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
    provider = ProviderConfigModel._default_manager.get(pk=provider_id)
    assert provider.extra_config == {}
