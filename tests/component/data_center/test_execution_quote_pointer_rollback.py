"""SQLite contract for the execution quote pointer rollback transaction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from django.db import connection, connections

from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
)
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
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageRawAuditBinding,
)
from apps.data_center.application.execution_quote_activation import (
    ExecutionQuotePublicationActivationBundle,
    stage_and_activate_execution_quote_candidate,
)
from apps.data_center.application.execution_quote_pointer_rollback import (
    ExecutionQuotePointerRollbackAuditObservation,
    ExecutionQuotePointerRollbackAuditReceipt,
    ExecutionQuotePointerRollbackCommand,
    ExecutionQuotePointerRollbackError,
    rollback_execution_quote_pointer,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.entities import RawAudit
from apps.data_center.execution_quote_pointer_rollback_composition import (
    build_production_execution_quote_pointer_rollback_bundle,
)
from apps.data_center.execution_quote_publication_composition import (
    build_production_execution_quote_publication_bundle,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from core.integration.data_center_execution_quote_rollback_audit import (
    CoreDataCenterExecutionQuoteRollbackAuditBridge,
)

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.data_center", "apps.audit"]
)

_DATASET_KEY = "equity.quote.snapshot"
_PUBLICATION_KEY = "execution"
_ASSET_CODE = "600000.SH"
_SOURCE = "execution-pointer-rollback-test"
_SOURCE_TYPE = "execution-pointer-rollback-test"
_TENANT_ID = "fixture-tenant"
_OWNER_ID = "fixture-owner"


@dataclass(frozen=True)
class _FenceFingerprint:
    complete_graph_hash: str = "f" * 64


@dataclass(frozen=True)
class _FenceResult:
    database_alias: str
    tenant_id: str
    owner_id: str
    generation: int
    fingerprint: _FenceFingerprint
    checked_at: datetime
    valid_until: datetime
    scope: str = "account_authority_complete_graph"


class _TestAuthorityFence:
    """Keep one synthetic complete authority result around a real DB transaction."""

    @contextmanager
    def fence_complete(self, proof: object):
        """Yield one fixture authority graph from the outermost transaction."""

        from django.db import transaction

        assert proof == "fixture-authority-proof"
        with transaction.atomic():
            checked_at = datetime.now(UTC)
            yield _FenceResult(
                database_alias="default",
                tenant_id=_TENANT_ID,
                owner_id=_OWNER_ID,
                generation=1,
                fingerprint=_FenceFingerprint(),
                checked_at=checked_at,
                valid_until=checked_at + timedelta(minutes=5),
            )


@dataclass(frozen=True)
class _TestAuthorityCapture:
    database_alias: str
    authority_fence: _TestAuthorityFence
    authority_proof: object


class _ScopeProvider:
    """Bind synthetic Audit events to the same fixture tenant and owner."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of.tzinfo is not None and as_of.utcoffset() is not None
        return AuditScopeRef(_TENANT_ID, _OWNER_ID)


def _reader_context() -> SystemAuditReaderContext:
    """Build the capability-bearing preflight context used by activation."""

    now = datetime.now(UTC)
    return SystemAuditReaderContext._from_authority(
        authority_source_id="fixture:authority",
        authority_source_version="1",
        actor_id="django-user:7",
        user_id=7,
        tenant_id=_TENANT_ID,
        owner_id=_OWNER_ID,
        authority_content_hash="a" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=now - timedelta(minutes=1),
        authority_valid_until=now + timedelta(hours=1),
    )


def _create_catalog(*, execution_freshness_seconds: int = 600) -> None:
    """Create one synthetic active quote policy and execution TTL contract."""

    dataset = DatasetKey(_DATASET_KEY, "2.0", "1.0")
    PublicationPolicyRepository().save(
        PublicationPolicy(
            dataset=dataset,
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=(
                "source",
                "observed_at",
                "fetched_at",
                "source_record_id",
                "raw_payload_hash",
                "raw_payload_scope",
                "fact_content_hash",
            ),
            retention_days=3650,
            policy_version="2",
        )
    )
    DatasetContractModel.objects.create(
        dataset_key=dataset.value,
        contract_version=dataset.contract_version,
        schema_version=dataset.schema_version,
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=[{"name": "snapshot_at", "value_type": "datetime"}],
        freshness_seconds=3600,
        execution_freshness_seconds=execution_freshness_seconds,
        active=True,
    )


def _create_quote_and_raw(*, observed_at: datetime) -> tuple[RawAudit, str, str]:
    """Persist one synthetic quote fact and its exact successful RawAudit."""

    fetched_at = observed_at + timedelta(seconds=2)
    run_id = str(uuid4())
    ingested_run_id = str(uuid4())
    source_record_id = f"fixture-quote:{uuid4().hex}"
    QuoteSnapshotModel.objects.create(
        asset_code=_ASSET_CODE,
        snapshot_at=observed_at,
        fetched_at=fetched_at,
        current_price=Decimal("10.1234"),
        bid=Decimal("10.1200"),
        ask=Decimal("10.1300"),
        prev_close=Decimal("9.9000"),
        source=_SOURCE,
        source_record_id=source_record_id,
        raw_payload_hash="b" * 64,
        quality_status="accepted",
        revision_number=1,
        contract_version="2.0",
        schema_version="1.0",
        ingested_run_id=ingested_run_id,
        extra={"raw_payload_scope": "batch_response_body"},
    )
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name=_SOURCE,
            capability="realtime_quote",
            request_params={"asset_code": _ASSET_CODE},
            status="ok",
            row_count=1,
            fetched_at=fetched_at,
            extra={"source_type": _SOURCE_TYPE},
            response_payload_hash="c" * 64,
            schema_fingerprint="d" * 64,
            parser_version="execution-pointer-rollback-fixture-v1",
            run_id=run_id,
            ingested_run_id=ingested_run_id,
        )
    )
    return raw, run_id, ingested_run_id


def _activation_bundle() -> ExecutionQuotePublicationActivationBundle:
    """Use the production activation repository with only fixture authority."""

    bundle = build_production_execution_quote_publication_bundle()
    return replace(
        bundle,
        audit_writer_factory=lambda: DjangoPublicationActivationAuditWriter(
            DjangoSystemAuditEventOutboxCoordinator()
        ),
        authority_capture=lambda **_kwargs: _TestAuthorityCapture(
            database_alias="default",
            authority_fence=_TestAuthorityFence(),
            authority_proof="fixture-authority-proof",
        ),
    )


def _activate_one(*, raw: RawAudit, run_id: str) -> CanonicalPublicationModel:
    """Stage and activate one fixture quote using the public execution path."""

    publication = stage_and_activate_execution_quote_candidate(
        bundle=_activation_bundle(),
        asset_codes=(_ASSET_CODE,),
        published_at=datetime.now(UTC),
        run_id=run_id,
        task_attempt_id=f"execution-pointer-rollback-test:{run_id}",
        raw_audit_bindings=(
            CurrentPublicationStageRawAuditBinding(
                reference=raw.exact_reference(),
                expected_source_type=_SOURCE_TYPE,
            ),
        ),
        preflight_context=_reader_context(),
    )
    return CanonicalPublicationModel.objects.get(publication_id=publication.publication_id)


def _rollback_bundle():
    """Use the production rollback repository and exact Audit bridge fixture."""

    bundle = build_production_execution_quote_pointer_rollback_bundle()
    audit = AppendDataPublicationRollbackAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )
    bridge = CoreDataCenterExecutionQuoteRollbackAuditBridge(audit)
    return replace(
        bundle,
        audit_writer_factory=lambda: bridge,
        authority_capture=lambda **_kwargs: _TestAuthorityCapture(
            database_alias="default",
            authority_fence=_TestAuthorityFence(),
            authority_proof="fixture-authority-proof",
        ),
    )


def _two_activated_publications(
    *, execution_freshness_seconds: int = 600
) -> tuple[CanonicalPublicationModel, CanonicalPublicationModel]:
    """Create two exact execution publications with stable synthetic source times."""

    _create_catalog(execution_freshness_seconds=execution_freshness_seconds)
    first_observed = datetime.now(UTC) - timedelta(seconds=30)
    first_raw, first_run, _first_ingested = _create_quote_and_raw(observed_at=first_observed)
    target = _activate_one(raw=first_raw, run_id=first_run)
    second_observed = datetime.now(UTC) - timedelta(seconds=10)
    second_raw, second_run, _second_ingested = _create_quote_and_raw(observed_at=second_observed)
    current = _activate_one(raw=second_raw, run_id=second_run)
    target.refresh_from_db()
    current.refresh_from_db()
    assert target.state == "superseded"
    assert current.state == "published"
    return target, current


def _command(
    *, target: CanonicalPublicationModel, current: CanonicalPublicationModel
) -> ExecutionQuotePointerRollbackCommand:
    """Bind the rollback request to both exact publication hashes and pointer epoch."""

    activation_id = str(
        uuid5(NAMESPACE_URL, f"agomtradepro:execution-quote-activation:{current.run_id}")
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_DATASET_KEY,
        publication_key=_PUBLICATION_KEY,
    )
    assert pointer.activation_id == activation_id
    return ExecutionQuotePointerRollbackCommand(
        rollback_id=str(uuid4()),
        target_publication_id=str(target.publication_id),
        target_publication_hash=target.publication_hash,
        expected_current_publication_id=str(current.publication_id),
        expected_current_publication_hash=current.publication_hash,
        expected_current_activation_id=activation_id,
        reason="restore verified execution quote snapshot",
        operator="fixture-operator",
        observed_at=datetime.now(UTC),
    )


def test_execution_pointer_rollback_restores_exact_snapshot_and_audit() -> None:
    """Restore the execution pointer while preserving publication and source hashes."""

    target, current = _two_activated_publications()
    target_hash = target.publication_hash
    current_hash = current.publication_hash
    command = _command(target=target, current=current)

    restored = rollback_execution_quote_pointer(
        command=command,
        bundle=_rollback_bundle(),
        preflight_context=_reader_context(),
    )

    target.refresh_from_db()
    current.refresh_from_db()
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_DATASET_KEY,
        publication_key=_PUBLICATION_KEY,
    )
    assert restored.publication.publication_id == str(target.publication_id)
    assert restored.publication.publication_hash == target_hash
    assert target.publication_hash == target_hash
    assert current.publication_hash == current_hash
    assert target.state == "published"
    assert current.state == "superseded"
    assert str(pointer.publication_id) == str(target.publication_id)
    assert pointer.publication_hash == target_hash
    assert pointer.activation_id == command.rollback_id
    rollback_event = SystemAuditEventModel.objects.get(
        event_type="data.publication.rolled_back",
        correlations__evidence_ref=command.rollback_id,
    )
    assert rollback_event.detail_schema == "data.publication.rolled_back.v2"
    assert rollback_event.detail["previous_pointer_activation_id"] == (
        command.expected_current_activation_id
    )
    outbox = SystemAuditOutboxModel.objects.get(event_id=rollback_event.event_id)
    assert restored.audit_receipt.event_id == rollback_event.event_id
    assert restored.audit_receipt.event_content_hash == rollback_event.content_hash
    assert restored.audit_receipt.outbox_id == outbox.outbox_id
    assert outbox.payload_hash == rollback_event.content_hash
    assert SystemAuditOutboxModel.objects.count() == 3


def test_exact_pointer_rollback_retry_requires_existing_event_and_outbox() -> None:
    """A complete replay succeeds; an event without its outbox is corruption."""

    target, current = _two_activated_publications()
    command = _command(target=target, current=current)
    bundle = _rollback_bundle()

    first = rollback_execution_quote_pointer(
        command=command,
        bundle=bundle,
        preflight_context=_reader_context(),
    )
    replay = rollback_execution_quote_pointer(
        command=command,
        bundle=bundle,
        preflight_context=_reader_context(),
    )
    assert first == replay
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.publication.rolled_back").count() == 1
    )
    assert SystemAuditOutboxModel.objects.count() == 3

    event = SystemAuditEventModel.objects.get(event_type="data.publication.rolled_back")
    quote_table = connection.ops.quote_name(SystemAuditOutboxModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {quote_table} WHERE event_id = %s",
            [event.event_id],
        )
    with pytest.raises(ExecutionQuotePointerRollbackError):
        rollback_execution_quote_pointer(
            command=command,
            bundle=bundle,
            preflight_context=_reader_context(),
        )
    assert not SystemAuditOutboxModel.objects.filter(event_id=event.event_id).exists()
    assert SystemAuditEventModel.objects.filter(event_id=event.event_id).count() == 1


def test_execution_pointer_rollback_rejects_stale_pointer_activation_cas() -> None:
    """A stale activation id cannot overwrite the pointer even with matching hashes."""

    target, current = _two_activated_publications()
    command = replace(
        _command(target=target, current=current),
        expected_current_activation_id=str(uuid4()),
    )

    with pytest.raises(ExecutionQuotePointerRollbackError):
        rollback_execution_quote_pointer(
            command=command,
            bundle=_rollback_bundle(),
            preflight_context=_reader_context(),
        )

    target.refresh_from_db()
    current.refresh_from_db()
    assert target.state == "superseded"
    assert current.state == "published"
    assert PublicationRollbackModel.objects.count() == 0
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.publication.rolled_back").count() == 0
    )


def test_execution_pointer_rollback_preserves_no_source_time_refresh() -> None:
    """A rollback cannot alter the immutable source observation that controls TTL."""

    target, current = _two_activated_publications()
    target_member = PublicationMemberModel.objects.get(publication_id=target.publication_id)
    original_observed_at = target_member.observed_at
    command = _command(target=target, current=current)

    rollback_execution_quote_pointer(
        command=command,
        bundle=_rollback_bundle(),
        preflight_context=_reader_context(),
    )

    target_member.refresh_from_db()
    target.refresh_from_db()
    assert target_member.observed_at == original_observed_at
    assert target.reinstated_at == command.observed_at


def test_execution_pointer_rollback_rechecks_target_ttl_after_required_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit latency cannot commit a pointer after the target's source TTL expires."""

    target, current = _two_activated_publications(execution_freshness_seconds=60)
    command = _command(target=target, current=current)
    target_member = PublicationMemberModel.objects.get(publication_id=target.publication_id)
    assert target_member.observed_at is not None
    deadline = target_member.observed_at + timedelta(seconds=60)
    before_expiry = deadline - timedelta(microseconds=1)
    phase = {"audit_completed": False}

    bundle = _rollback_bundle()
    canonical_writer = bundle.audit_writer_factory()

    class _AuditBoundary:
        database_alias = canonical_writer.database_alias

        def execute_in_caller_transaction(
            self,
            observation: ExecutionQuotePointerRollbackAuditObservation,
            *,
            exact_replay: bool,
        ) -> ExecutionQuotePointerRollbackAuditReceipt:
            receipt = canonical_writer.execute_in_caller_transaction(
                observation, exact_replay=exact_replay
            )
            phase["audit_completed"] = True
            return receipt

    class _Clock:
        @staticmethod
        def now() -> datetime:
            return deadline if phase["audit_completed"] else before_expiry

    import apps.data_center.infrastructure.execution_quote_pointer_rollback_repository as repo_module

    monkeypatch.setattr(repo_module, "timezone", _Clock)
    with pytest.raises(ExecutionQuotePointerRollbackError):
        rollback_execution_quote_pointer(
            command=command,
            bundle=replace(bundle, audit_writer_factory=lambda: _AuditBoundary()),
            preflight_context=_reader_context(),
        )

    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_DATASET_KEY,
        publication_key=_PUBLICATION_KEY,
    )
    target.refresh_from_db()
    current.refresh_from_db()
    assert str(pointer.publication_id) == str(current.publication_id)
    assert target.state == "superseded"
    assert current.state == "published"
    assert PublicationRollbackModel.objects.count() == 0
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.publication.rolled_back").count() == 0
    )
    assert SystemAuditOutboxModel.objects.count() == 2


def test_execution_pointer_rollback_competing_current_pointer_cas_is_serialized() -> None:
    """Only one of two concurrent rollbacks from the same current epoch can commit."""

    if connection.vendor != "postgresql":
        pytest.skip("Independent connection CAS proof runs on the PostgreSQL component database")
    target, current = _two_activated_publications()
    base = _command(target=target, current=current)
    commands = (
        base,
        replace(base, rollback_id=str(uuid4())),
    )
    barrier = Barrier(2)

    def _attempt(item: ExecutionQuotePointerRollbackCommand) -> str:
        connections.close_all()
        try:
            barrier.wait(timeout=10)
            rollback_execution_quote_pointer(
                command=item,
                bundle=_rollback_bundle(),
                preflight_context=_reader_context(),
            )
            return "committed"
        except ExecutionQuotePointerRollbackError as error:
            return str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(_attempt, commands))

    assert sorted(outcomes) == [
        "committed",
        "execution quote pointer compare-and-swap failed",
    ]
    assert PublicationRollbackModel.objects.count() == 1
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.publication.rolled_back").count() == 1
    )
    assert SystemAuditOutboxModel.objects.count() == 3
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=_DATASET_KEY,
        publication_key=_PUBLICATION_KEY,
    )
    assert pointer.publication_id == target.publication_id


def test_rollback_command_accepts_unicode_reason_and_normalizes_offset_time() -> None:
    """The operator explanation is human text and operation instants are canonical UTC."""

    from datetime import timezone

    observed_at = datetime(2026, 10, 16, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    command = ExecutionQuotePointerRollbackCommand(
        rollback_id=str(uuid4()),
        target_publication_id=str(uuid4()),
        target_publication_hash="a" * 64,
        expected_current_publication_id=str(uuid4()),
        expected_current_publication_hash="b" * 64,
        expected_current_activation_id=str(uuid4()),
        reason="恢复经核实的盘中报价快照",
        operator="fixture-operator",
        observed_at=observed_at,
    )
    assert command.observed_at == observed_at.astimezone(UTC)
