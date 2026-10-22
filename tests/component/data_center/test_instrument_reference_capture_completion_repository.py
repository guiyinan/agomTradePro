"""Counterexamples for claim fencing and atomic completion receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from django.db import close_old_connections, connection, models
from pytest_django.plugin import DjangoDbBlocker

from apps.data_center.application.instrument_reference_capture import (
    CaptureInvocationMode,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureLease,
)
from apps.data_center.application.instrument_reference_source import (
    InstrumentReferenceAuditOccurrence,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.control_plane import SyncItemState, SyncRunStatus
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureClaimHistory,
    CaptureClaimMarker,
    CaptureClaimPayload,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
    make_instrument_reference_mapping_record,
    make_instrument_reference_snapshot_record,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
)
from apps.data_center.infrastructure.instrument_reference_capture_completion_repository import (
    DjangoInstrumentReferenceCaptureCompletionRepository,
)
from apps.data_center.infrastructure.instrument_reference_capture_receipt import (
    CaptureCompletionMarker,
    scope_checkpoint_name,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncItemAttemptModel,
    SyncRunModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

_NOW = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)
_SNAPSHOT_ID = UUID("8d407a7e-9220-40ce-bdb1-5eb735e557bd")
pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Capture completion concurrency requires the Native PostgreSQL test database",
)


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use the explicitly configured Native PostgreSQL test database."""

    return native_postgres_test_database


@pytest.fixture(autouse=True)
def _capture_native_test_schema(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Guard setup and cleanup while isolating only capture control tables."""

    model_types: tuple[type[models.Model], ...] = (
        RawPayloadModel,
        RawAuditModel,
        InstrumentReferenceMappingModel,
        InstrumentReferenceSnapshotModel,
        SyncRunModel,
        SyncBatchModel,
        SyncCheckpointModel,
        SyncItemAttemptModel,
    )

    def _verify_database() -> None:
        """Require PostgreSQL's active database to match TEST.NAME."""

        assert_native_postgres_test_database(expected_name=django_db_setup)

    with django_db_blocker.unblock():
        _verify_database()
        with isolated_schema(model_types, before_cleanup=_verify_database):
            try:
                yield
            finally:
                _verify_database()


class _SnapshotRepository:
    """Keep exact mapping and snapshot receipts for control-plane tests."""

    def __init__(self, mapping: InstrumentReferenceMappingRecord) -> None:
        """Bind one request mapping and start without a snapshot receipt."""

        self.mapping = mapping
        self.record: InstrumentReferenceSnapshotRecord | None = None
        self.save_count = 0

    @property
    def unit_of_work_key(self) -> str:
        """Declare the same database transaction identity as production."""

        return "django:default"

    def get_mapping(self, mapping_record_id: UUID) -> InstrumentReferenceMappingRecord | None:
        """Return only the exact fixture mapping identity."""

        return self.mapping if mapping_record_id == self.mapping.mapping_record_id else None

    def save_snapshot(
        self,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Create one deterministic receipt and count only the first insert."""

        self.save_count += 1
        if self.record is None:
            self.record = make_instrument_reference_snapshot_record(
                content,
                snapshot_id=_SNAPSHOT_ID,
                recorded_at=_NOW + timedelta(seconds=1),
            )
        elif self.record.content != content:
            raise AssertionError("snapshot content changed across completion retry")
        return self.record

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Return the stored receipt only for its exact snapshot ID."""

        if self.record is None or self.record.snapshot_id != snapshot_id:
            return None
        return self.record


class _CaptureCompletionRepository(DjangoInstrumentReferenceCaptureCompletionRepository):
    """Replace snapshot-table access while keeping the real control-plane rows."""

    def _snapshot_rows(self, run_id: UUID) -> list[InstrumentReferenceSnapshotModel]:
        """Expose the repository receipt as the exact indexed snapshot row."""

        del run_id
        record = cast(_SnapshotRepository, self._snapshot_repository).record
        if record is None:
            return []
        return [
            cast(
                InstrumentReferenceSnapshotModel,
                SimpleNamespace(
                    snapshot_id=record.snapshot_id,
                    content_hash=record.content_hash,
                    record_digest=record.record_digest,
                ),
            )
        ]


def _request_and_content() -> tuple[
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceSnapshotContent,
]:
    """Build a complete empty-row stock-basic source snapshot fixture."""

    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key="fixture.stock-basic",
        api_name="stock_basic",
        fields=("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date"),
        exchange_scope=("SSE",),
        list_status_scope=("L",),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    mapping = make_instrument_reference_mapping_record(
        InstrumentReferenceMappingContent(
            mapping_id="fixture.mapping",
            mapping_version="fixture-v1",
            source_crosswalk=crosswalk,
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-market", "FIXTURE"),),
        ),
        mapping_record_id=UUID("c5d7a91a-17f2-43a2-8f55-0a74789be639"),
        recorded_at=_NOW,
    )
    request = InstrumentReferenceCaptureRequest(
        capture_id=UUID("84c776c3-0db4-4aed-9d2c-62e18b917ed5"),
        provider_contract=contract,
        provider_route_id="tushare.stock_basic",
        provider_route_revision="fixture-route-rev-1",
        provider_configuration_id=17,
        mapping_record=mapping,
    )
    scope = request.scopes[0]
    occurrence = InstrumentReferenceOccurrence(
        occurrence_id=request.occurrence_id(scope),
        exchange=scope.exchange,
        list_status=scope.list_status,
        raw_audit_reference=RawAuditReference(
            raw_audit_id="184467",
            version="fixture-v1",
            content_hash="a" * 64,
            run_id=str(request.identity.run_id),
            ingested_run_id=str(request.identity.batch_id),
        ),
        raw_payload_id="e3b0c442-98fc-1c14-9afc-d8c2f8b44a21",
        raw_payload_hash="sha256:" + "b" * 64,
        response_body_sha256="c" * 64,
        response_completed_at=_NOW,
        row_count=0,
    )
    candidate = InstrumentReferenceCandidate(
        provider_contract=contract,
        crosswalk=crosswalk,
        occurrences=(occurrence,),
        records=(),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=request.identity.run_id,
        mapping_record=mapping,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=request.identity.capture_id,
                candidate=candidate,
            ),
        ),
    )
    return request, content


def _history_and_lease(
    request: InstrumentReferenceCaptureRequest,
) -> tuple[CaptureClaimHistory, InstrumentReferenceCaptureLease]:
    """Issue one valid first claim for pure fencing and marker tests."""

    capability = CaptureOwnerCapability(b"first-owner-capability-00000000".ljust(32, b"0"))
    epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    history = CaptureClaimHistory.from_checkpoint_rows(
        request.request_sha256,
        ((CaptureClaimMarker.for_epoch(1).cursor_name, "v1"),),
        ((CaptureClaimPayload.for_claim(epoch).cursor_name, epoch.to_checkpoint_value()),),
    )
    return history, InstrumentReferenceCaptureLease(
        identity=request.identity,
        request_sha256=request.request_sha256,
        epoch=epoch,
        owner_capability=capability,
    )


def _persist_scope_pointers(
    request: InstrumentReferenceCaptureRequest,
    content: InstrumentReferenceSnapshotContent,
) -> None:
    """Persist the exact response and raw-audit receipts needed for completion."""

    occurrence = content.fetch_rounds[0].candidate.occurrences[0]
    scope = request.scopes[0]
    common = {
        "run_id": request.identity.run_id,
        "batch_id": request.identity.batch_id,
        "state": SyncItemState.SUCCEEDED.value,
        "processed": 0,
        "failed": 0,
        "recorded_at": _NOW,
        "error_code": "",
    }
    SyncCheckpointModel.objects.create(
        **common,
        cursor_name=scope_checkpoint_name(scope, "response"),
        cursor_value=occurrence.raw_payload_id,
    )
    SyncCheckpointModel.objects.create(
        **common,
        cursor_name=scope_checkpoint_name(scope, "audit"),
        cursor_value=occurrence.raw_audit_reference.raw_audit_id,
    )


def _persisted_completion_fixture() -> tuple[
    DjangoInstrumentReferenceCaptureCompletionRepository,
    DjangoInstrumentReferenceSnapshotRepository,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceSnapshotContent,
]:
    """Compose real default-database raw evidence and snapshot persistence."""

    base_request, _base_content = _request_and_content()
    raw_payloads = RawLandingRepository()
    raw_audits = RawAuditRepository()
    snapshots = DjangoInstrumentReferenceSnapshotRepository(
        cast(RawAuditRepositoryProtocol, raw_audits),
        raw_payloads,
        clock=lambda: _NOW + timedelta(seconds=5),
    )
    mapping = snapshots.save_mapping(base_request.mapping_record.content)
    request = replace(base_request, mapping_record=mapping)
    scope = request.scopes[0]
    contract = request.provider_contract
    provider_response: dict[str, object] = {
        "code": 0,
        "msg": None,
        "data": {"fields": list(contract.fields), "items": []},
    }
    body = canonical_provider_response_json(provider_response).encode("utf-8")
    response = ProviderResponseCapture(
        body=body,
        payload=provider_response,
        body_sha256=hashlib.sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_NOW,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.DIRECT,
    )
    request_params: dict[str, object] = {
        "api_name": contract.api_name,
        "fields": contract.fields_csv,
        "params": {"exchange": scope.exchange, "list_status": scope.list_status},
    }
    reference = RetainProviderResponsePayloadUseCase(raw_payloads).execute(
        response,
        provider_name=contract.provider_name,
        dataset_key=contract.dataset_key,
        api_name=contract.api_name,
        request_params=request_params,
    )
    raw_payload = raw_payloads.get_by_id(reference.payload_id)
    assert raw_payload is not None
    audit = DjangoInstrumentReferenceRawAuditOccurrenceWriter(
        cast(RawAuditRepositoryProtocol, raw_audits)
    ).record(
        InstrumentReferenceAuditOccurrence(
            occurrence_id=request.occurrence_id(scope),
            run_id=request.identity.run_id,
            ingested_run_id=request.identity.batch_id,
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            contract_hash=contract.content_hash,
            api_name=contract.api_name,
            dataset_key=contract.dataset_key,
            exchange=scope.exchange,
            list_status=scope.list_status,
            fields=contract.fields_csv,
            row_count=0,
            response_reference=reference,
            raw_payload=raw_payload,
        )
    )
    occurrence = InstrumentReferenceOccurrence(
        occurrence_id=request.occurrence_id(scope),
        exchange=scope.exchange,
        list_status=scope.list_status,
        raw_audit_reference=audit.raw_audit_reference,
        raw_payload_id=audit.raw_payload_id,
        raw_payload_hash=audit.raw_payload_hash,
        response_body_sha256=audit.response_body_sha256,
        response_completed_at=reference.response_completed_at,
        row_count=0,
    )
    candidate = InstrumentReferenceCandidate(
        provider_contract=contract,
        crosswalk=request.mapping_record.content.source_crosswalk,
        occurrences=(occurrence,),
        records=(),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=request.identity.run_id,
        mapping_record=request.mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=request.identity.capture_id,
                candidate=candidate,
            ),
        ),
    )
    repository = DjangoInstrumentReferenceCaptureCompletionRepository(
        snapshots,
        clock=lambda: _NOW,
    )
    return repository, snapshots, request, content


def test_resume_supersedes_the_old_epoch_without_ttl_claims() -> None:
    """Reject an epoch replaced by RESUME as the current lease fence."""

    request, _content = _request_and_content()
    history, old_lease = _history_and_lease(request)
    next_capability = CaptureOwnerCapability(b"second-owner-capability-000000".ljust(32, b"0"))
    next_epoch = CaptureClaimEpoch.issue(
        2,
        request.request_sha256,
        history.latest.claim_sha256 if history.latest is not None else None,
        next_capability,
    )
    resumed_history = CaptureClaimHistory.from_checkpoint_rows(
        request.request_sha256,
        (
            (CaptureClaimMarker.for_epoch(1).cursor_name, "v1"),
            (CaptureClaimMarker.for_epoch(2).cursor_name, "v1"),
        ),
        (
            (
                CaptureClaimPayload.for_claim(old_lease.epoch).cursor_name,
                old_lease.epoch.to_checkpoint_value(),
            ),
            (
                CaptureClaimPayload.for_claim(next_epoch).cursor_name,
                next_epoch.to_checkpoint_value(),
            ),
        ),
    )
    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        DjangoInstrumentReferenceCaptureCompletionRepository._require_current_history(
            resumed_history,
            old_lease,
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_LEASE_STALE"


def test_completed_snapshot_without_receipt_marker_is_rejected() -> None:
    """Reject a snapshot row when its transaction receipt is absent."""

    request, _content = _request_and_content()
    history, _lease = _history_and_lease(request)
    repository = object.__new__(DjangoInstrumentReferenceCaptureCompletionRepository)

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        repository._read_completed_snapshot(
            request,
            cast(SyncRunModel, object()),
            cast(SyncBatchModel, object()),
            history,
            {},
            None,
            [],
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_MISSING"


def test_completion_marker_with_wrong_claim_seal_is_rejected() -> None:
    """Reject a marker whose epoch claim seal does not match the claim chain."""

    request, _content = _request_and_content()
    history, lease = _history_and_lease(request)
    marker = CaptureCompletionMarker(
        request_sha256=request.request_sha256,
        epoch=lease.epoch.epoch,
        claim_sha256="f" * 64,
        snapshot_id=_SNAPSHOT_ID,
        snapshot_content_hash="sha256:" + "d" * 64,
        snapshot_record_digest="sha256:" + "e" * 64,
    )
    snapshot_row = cast(
        InstrumentReferenceSnapshotModel,
        SimpleNamespace(
            snapshot_id=_SNAPSHOT_ID,
            content_hash="d" * 64,
            record_digest="sha256:" + "e" * 64,
        ),
    )
    repository = object.__new__(DjangoInstrumentReferenceCaptureCompletionRepository)

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        repository._read_completed_snapshot(
            request,
            cast(SyncRunModel, object()),
            cast(SyncBatchModel, object()),
            history,
            {},
            marker,
            [snapshot_row],
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_MISMATCH"


@pytest.mark.django_db(transaction=True)
def test_resumed_claim_prevents_old_epoch_from_persisting_snapshot() -> None:
    """Reject an old lease before snapshot persistence after RESUME advances epoch."""

    repository, snapshots, request, content = _persisted_completion_fixture()
    first = repository.claim(
        InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.NORMAL)
    )
    assert first.lease is not None
    _persist_scope_pointers(request, content)
    resumed = repository.claim(
        InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.RESUME)
    )
    assert resumed.lease is not None
    assert resumed.lease.epoch.epoch == first.lease.epoch.epoch + 1

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        repository.complete_snapshot(first.lease, content)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_LEASE_STALE"
    assert (
        InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id).count() == 0
    )
    assert repository.is_current(resumed.lease)
    assert not repository.is_current(first.lease)


@pytest.mark.django_db(transaction=True)
def test_tampered_progress_metadata_cannot_be_used_to_complete_capture() -> None:
    """Reject inconsistent progress checkpoint metadata before writing a snapshot."""

    repository, _snapshots, request, content = _persisted_completion_fixture()
    acquired = repository.claim(
        InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.NORMAL)
    )
    assert acquired.lease is not None
    _persist_scope_pointers(request, content)
    SyncCheckpointModel.objects.filter(
        run_id=request.identity.run_id,
        cursor_name=scope_checkpoint_name(request.scopes[0], "audit"),
    ).update(
        state=SyncItemState.FAILED.value,
        processed=1,
        failed=1,
        error_code="TAMPERED",
    )

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        repository.complete_snapshot(acquired.lease, content)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
    assert (
        InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id).count() == 0
    )


@pytest.mark.django_db(transaction=True)
def test_terminal_write_failure_rolls_back_snapshot_and_completion_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll back snapshot and marker when final run accounting cannot be written."""

    repository, _snapshots, request, content = _persisted_completion_fixture()
    acquired = repository.claim(
        InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.NORMAL)
    )
    assert acquired.lease is not None
    _persist_scope_pointers(request, content)

    def _fail_terminal_run_save(
        run: SyncRunModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Fail after snapshot and completion marker writes reach the transaction."""

        del run, args, kwargs
        raise RuntimeError("fixture final run write failure")

    monkeypatch.setattr(SyncRunModel, "save", _fail_terminal_run_save)
    with pytest.raises(RuntimeError, match="fixture final run write failure"):
        repository.complete_snapshot(acquired.lease, content)

    assert (
        InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id).count() == 0
    )
    assert (
        SyncCheckpointModel.objects.filter(
            run_id=request.identity.run_id,
            cursor_name="ircap.v1.complete",
        ).count()
        == 0
    )
    assert SyncRunModel.objects.get(run_id=request.identity.run_id).status == "fetching"
    assert SyncBatchModel.objects.get(batch_id=request.identity.batch_id).state == "running"


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_completion_replays_return_one_sealed_snapshot() -> None:
    """Serialize concurrent finalization and return the same persisted receipt."""

    repository, _snapshots, request, content = _persisted_completion_fixture()
    invocation = InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.NORMAL)
    acquired = repository.claim(invocation)
    assert acquired.lease is not None
    _persist_scope_pointers(request, content)
    start = Barrier(2)

    def _finish() -> InstrumentReferenceSnapshotRecord:
        """Start one completion attempt from an independent database connection."""

        close_old_connections()
        try:
            start.wait()
            return repository.complete_snapshot(acquired.lease, content)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_finish)
        second = executor.submit(_finish)
        records = (first.result(), second.result())

    assert records[0] == records[1]
    assert (
        InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id).count() == 1
    )
    run = SyncRunModel.objects.get(run_id=request.identity.run_id)
    batch = SyncBatchModel.objects.get(batch_id=request.identity.batch_id)
    completion_rows = SyncCheckpointModel.objects.filter(
        run_id=request.identity.run_id,
        cursor_name="ircap.v1.complete",
    )
    assert run.status == SyncRunStatus.STORED.value
    assert run.outcome == "success"
    assert batch.state == SyncItemState.SUCCEEDED.value
    assert completion_rows.count() == 1
