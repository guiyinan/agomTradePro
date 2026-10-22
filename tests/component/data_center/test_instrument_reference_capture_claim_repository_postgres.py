"""Exercise durable instrument-reference capture leases on the real control plane."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.data_center.application.instrument_reference_capture import (
    CaptureClaimDisposition,
    CaptureInvocationMode,
    InstrumentReferenceCaptureClaimResult,
    InstrumentReferenceCaptureInvocation,
)
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceMappingUseCase,
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncCheckpoint,
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceSnapshotContent,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncBatchRepository,
    SyncCheckpointRepository,
    SyncRunRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)
from apps.data_center.infrastructure.instrument_reference_capture_claim_repository import (
    DjangoInstrumentReferenceCaptureClaimRepository,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.sync_item_attempt_models import SyncItemAttemptModel
from apps.data_center.infrastructure.sync_item_attempt_repository import (
    SyncItemAttemptRepository,
)
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    TushareInstrumentReferenceSource,
    TushareStockBasicClientPort,
)
from tests.support.isolated_schema import isolated_schema
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])

_FIELDS = ("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date")
_NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    """Create only the source-evidence and control-plane tables needed here."""

    with isolated_schema(
        (
            RawPayloadModel,
            RawAuditModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
            SyncRunModel,
            SyncBatchModel,
            SyncCheckpointModel,
            SyncItemAttemptModel,
        )
    ):
        yield


class _StockBasicSession(_Session):
    """Return deterministic stock-basic bodies without making network calls."""

    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))

    def post(self, url: str, **kwargs: object) -> _Response:
        """Capture the request and answer each exact listing-status scope."""

        del url
        self.calls.append(kwargs)
        request = kwargs.get("json")
        assert isinstance(request, dict)
        params = request.get("params")
        assert isinstance(params, dict)
        rows: list[list[object]] = []
        if params.get("list_status") == "L":
            rows = [["600000.SH", "Fixture bank", "SSE", "fixture-main", "L", "20200102", ""]]
        response = _Response(
            (
                '{"code":0,"msg":null,"data":{"fields":'
                + json.dumps(list(_FIELDS))
                + ',"items":'
                + json.dumps(rows)
                + "}}"
            ).encode("utf-8")
        )
        self.response = response
        return response


def _persisted_capture_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DjangoInstrumentReferenceSnapshotRepository,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceSnapshotContent,
]:
    """Build exact audited source rounds and a mapping bound to one capture ID."""

    session = _StockBasicSession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    payload_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payload_repository)
    dataset_key = "fixture.instrument-reference.stock-basic"
    client = tushare_client.create_tushare_pro_client(
        token="fixture-only-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.instrument-reference.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key=dataset_key,
        api_name="stock_basic",
        fields=_FIELDS,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    raw_audit_repository = RawAuditRepository()
    snapshot_repository = DjangoInstrumentReferenceSnapshotRepository(
        cast(RawAuditRepositoryProtocol, raw_audit_repository),
        payload_repository,
        clock=timezone.now,
    )
    mapping_content = InstrumentReferenceMappingContent(
        mapping_id="fixture.instrument-reference-map",
        mapping_version="fixture-v1",
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
    )
    mapping_record = SaveInstrumentReferenceMappingUseCase(snapshot_repository).execute(
        mapping_content
    )
    capture_id = uuid4()
    request = InstrumentReferenceCaptureRequest(
        capture_id=capture_id,
        provider_contract=contract,
        provider_route_id="fixture.stock-basic-route",
        provider_route_revision="fixture-route-v1",
        provider_configuration_id=1,
        mapping_record=mapping_record,
    )
    source = TushareInstrumentReferenceSource(
        cast(TushareStockBasicClientPort, client),
        payload_repository,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(raw_audit_repository),
        provider_contract=contract,
        exchange_suffix_crosswalk=crosswalk,
    )
    candidates = (
        source.fetch_candidate(
            run_id=request.identity.run_id, ingested_run_id=request.identity.batch_id
        ),
        source.fetch_candidate(
            run_id=request.identity.run_id, ingested_run_id=request.identity.batch_id
        ),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=request.identity.run_id,
        mapping_record=mapping_record,
        fetch_rounds=tuple(
            InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidate)
            for candidate in candidates
        ),
    )
    return snapshot_repository, request, content


def _attempt(batch: SyncBatch, *, asset_code: str = "600000.SH") -> SyncItemAttempt:
    """Build a valid running QUOTE attempt for generic-writer fence checks."""

    return SyncItemAttempt(
        attempt_id=str(uuid4()),
        run_id=batch.run_id,
        batch_id=batch.batch_id,
        dataset_key=batch.dataset_key,
        asset_code=asset_code,
        phase=SyncItemAttemptPhase.QUOTE,
        attempt_number=1,
        state=SyncItemAttemptState.RUNNING,
        execution_token="capture-fence-test",
        started_at=_NOW,
        universe_hash="a" * 64,
        authority_content_hash="b" * 64,
    )


def test_claim_normal_retry_resume_and_reject_unfenced_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep one owner at a time and reject snapshots without fenced completion."""

    snapshot_repository, request, content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    normal = InstrumentReferenceCaptureInvocation(request)
    first = repository.claim(normal)
    persisted_run = SyncRunModel.objects.get(run_id=request.identity.run_id)
    request_checkpoints = list(
        SyncCheckpointModel.objects.filter(
            run_id=request.identity.run_id,
            cursor_name__startswith="ircap.v1.request.",
        ).order_by("cursor_name", "checkpoint_id")
    )
    request_descriptor = "".join(row.cursor_value for row in request_checkpoints)
    assert first.request_sha256 == request.request_sha256
    assert persisted_run.config_snapshot_hash == ""
    assert request_descriptor == request.canonical_request
    assert hashlib.sha256(request_descriptor.encode("ascii")).hexdigest() == request.request_sha256
    assert first.disposition is CaptureClaimDisposition.ACQUIRED
    assert first.lease is not None
    assert repository.is_current(first.lease)

    retry = repository.claim(normal)
    assert retry.disposition is CaptureClaimDisposition.IN_PROGRESS
    assert retry.lease is None
    resumed = repository.claim(
        InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.RESUME)
    )
    assert resumed.disposition is CaptureClaimDisposition.ACQUIRED
    assert resumed.lease is not None
    assert resumed.lease.epoch.epoch == first.lease.epoch.epoch + 1
    assert not repository.is_current(first.lease)
    assert repository.is_current(resumed.lease)

    SaveInstrumentReferenceSnapshotUseCase(snapshot_repository).execute(content)
    run_before = SyncRunModel.objects.filter(run_id=request.identity.run_id).values().get()
    batch_before = SyncBatchModel.objects.filter(batch_id=request.identity.batch_id).values().get()
    checkpoints_before = list(
        SyncCheckpointModel.objects.filter(run_id=request.identity.run_id)
        .order_by("cursor_name", "checkpoint_id")
        .values()
    )
    snapshots_before = list(
        InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id)
        .order_by("snapshot_id")
        .values()
    )
    attempts_before = list(
        SyncItemAttemptModel.objects.filter(run_id=request.identity.run_id)
        .order_by("attempt_id")
        .values()
    )
    assert len(snapshots_before) == 1
    with pytest.raises(InstrumentReferenceCaptureContractError) as error:
        repository.claim(
            InstrumentReferenceCaptureInvocation(request, CaptureInvocationMode.RESUME)
        )
    assert error.value.code == "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_INVALID"
    assert not repository.is_current(resumed.lease)
    assert SyncRunModel.objects.filter(run_id=request.identity.run_id).values().get() == run_before
    assert (
        SyncBatchModel.objects.filter(batch_id=request.identity.batch_id).values().get()
        == batch_before
    )
    assert (
        list(
            SyncCheckpointModel.objects.filter(run_id=request.identity.run_id)
            .order_by("cursor_name", "checkpoint_id")
            .values()
        )
        == checkpoints_before
    )
    assert (
        list(
            InstrumentReferenceSnapshotModel.objects.filter(run_id=request.identity.run_id)
            .order_by("snapshot_id")
            .values()
        )
        == snapshots_before
    )
    assert (
        list(
            SyncItemAttemptModel.objects.filter(run_id=request.identity.run_id)
            .order_by("attempt_id")
            .values()
        )
        == attempts_before
    )


def test_claim_rejects_same_capture_id_with_a_different_request_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not treat a reused UUID with different route/config as a retry."""

    snapshot_repository, request, _content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    acquired = repository.claim(InstrumentReferenceCaptureInvocation(request))
    assert acquired.lease is not None
    altered = InstrumentReferenceCaptureRequest(
        capture_id=request.capture_id,
        provider_contract=request.provider_contract,
        provider_route_id=request.provider_route_id,
        provider_route_revision="fixture-route-v2",
        provider_configuration_id=request.provider_configuration_id,
        mapping_record=request.mapping_record,
    )
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.claim(InstrumentReferenceCaptureInvocation(altered))
    assert SyncRunModel.objects.count() == 1
    assert SyncBatchModel.objects.count() == 1


@pytest.mark.parametrize(
    "field,value", [("processed", 1), ("state", "failed"), ("error_code", "tampered")]
)
def test_claim_rejects_modified_checkpoint_envelope_metadata(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Validate row metadata as well as the canonical descriptor and epoch hashes."""

    snapshot_repository, request, _content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    repository.claim(InstrumentReferenceCaptureInvocation(request))
    row = SyncCheckpointModel.objects.filter(run_id=request.identity.run_id).first()
    assert row is not None
    changed = SyncCheckpointModel.objects.filter(checkpoint_id=row.checkpoint_id).update(
        **{field: value}
    )
    assert changed == 1
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.claim(InstrumentReferenceCaptureInvocation(request))


def test_claim_rejects_request_descriptor_chunk_index_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject gaps, duplicates, and extra descriptor chunks even with valid row seals."""

    _snapshot_repository, request, _content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        _snapshot_repository, clock=lambda: _NOW
    )
    repository.claim(InstrumentReferenceCaptureInvocation(request))
    row = (
        SyncCheckpointModel.objects.filter(
            run_id=request.identity.run_id,
            cursor_name__startswith="ircap.v1.request.",
        )
        .order_by("cursor_name", "checkpoint_id")
        .first()
    )
    assert row is not None
    prefix, raw_index = row.cursor_name.rsplit(".", 1)
    total_text = prefix.rsplit(".", 1)[1]
    assert raw_index.isdecimal() and total_text.isdecimal()
    changed = SyncCheckpointModel.objects.filter(checkpoint_id=row.checkpoint_id).update(
        cursor_name=f"{prefix}.{int(total_text) + 1:06d}"
    )
    assert changed == 1
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.claim(InstrumentReferenceCaptureInvocation(request))


def test_unclaimed_snapshot_and_generic_control_plane_writers_are_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject orphan completion, then reject generic writes to the acquired namespace."""

    snapshot_repository, request, content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    SaveInstrumentReferenceSnapshotUseCase(snapshot_repository).execute(content)
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.claim(InstrumentReferenceCaptureInvocation(request))
    assert SyncRunModel.objects.count() == 0
    assert SyncBatchModel.objects.count() == 0

    # A fresh identity is independent of the retained orphaned snapshot row.
    request = InstrumentReferenceCaptureRequest(
        capture_id=uuid4(),
        provider_contract=request.provider_contract,
        provider_route_id=request.provider_route_id,
        provider_route_revision=request.provider_route_revision,
        provider_configuration_id=request.provider_configuration_id,
        mapping_record=request.mapping_record,
    )
    result = repository.claim(InstrumentReferenceCaptureInvocation(request))
    assert result.disposition is CaptureClaimDisposition.ACQUIRED
    run = SyncRunModel.objects.get(run_id=request.identity.run_id).to_domain()
    batch = SyncBatchModel.objects.get(batch_id=request.identity.batch_id).to_domain()
    normal_checkpoint = SyncCheckpoint(
        checkpoint_id=str(uuid4()),
        run_id=batch.run_id,
        batch_id=batch.batch_id,
        cursor_name="ordinary-cursor",
        cursor_value="value",
        recorded_at=_NOW,
    )
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncRunRepository().save(run)
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncBatchRepository().save(batch)
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncCheckpointRepository().save(normal_checkpoint)
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncCheckpointRepository().save(
            SyncCheckpoint(
                checkpoint_id=str(uuid4()),
                run_id=str(uuid4()),
                batch_id=str(uuid4()),
                cursor_name="ircap.v1.claim.marker.000001",
                cursor_value="1",
                recorded_at=_NOW,
            )
        )
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncRunRepository().save(
            SyncRun(
                run_id=str(uuid4()),
                dataset_key="fixture.instrument-reference.stock-basic",
                trigger="instrument_reference_capture",
                status=SyncRunStatus.REQUESTED,
                outcome="blocked",
                started_at=_NOW,
            )
        )
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncBatchRepository().save(
            SyncBatch(
                batch_id=str(uuid4()),
                run_id=str(uuid4()),
                dataset_key="fixture.instrument-reference.stock-basic",
                provider_name="tushare",
                idempotency_key="instrument-reference-capture.v1:substituted",
                started_at=_NOW,
            )
        )
    before = SyncItemAttemptModel.objects.count()
    with pytest.raises(InstrumentReferenceCaptureContractError):
        SyncItemAttemptRepository().begin(_attempt(batch))
    assert SyncItemAttemptModel.objects.count() == before


def test_attempt_finish_and_recovery_recheck_reserved_namespace_under_parent_locks() -> None:
    """A later marker reserves an ordinary batch before either terminal writer mutates it."""

    run_id = str(uuid4())
    run = SyncRunRepository().save(
        SyncRun(
            run_id=run_id,
            dataset_key="fixture.regular.dataset",
            trigger="pytest",
            status=SyncRunStatus.REQUESTED,
            outcome="blocked",
            started_at=_NOW,
        )
    )
    batch = SyncBatchRepository().save(
        SyncBatch(
            batch_id=str(uuid4()),
            run_id=run.run_id,
            dataset_key=run.dataset_key,
            provider_name="fixture",
            idempotency_key=f"fixture:{uuid4()}",
            state=SyncItemState.RUNNING,
            requested=2,
            started_at=_NOW,
        )
    )
    repository = SyncItemAttemptRepository()
    first = repository.begin(_attempt(batch, asset_code="600000.SH"))
    second = repository.begin(_attempt(batch, asset_code="600001.SH"))
    SyncCheckpointModel.objects.create(
        checkpoint_id=uuid4(),
        run_id=UUID(batch.run_id),
        batch_id=UUID(batch.batch_id),
        cursor_name="ircap.v1.claim.marker.000001",
        cursor_value="capture-marker",
        state=SyncItemState.SUCCEEDED.value,
        processed=0,
        failed=0,
        recorded_at=_NOW,
        error_code="",
    )
    terminal = first.finish(
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=_NOW.replace(second=1),
        stored_count=1,
    )
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.finish(terminal)
    with pytest.raises(InstrumentReferenceCaptureContractError):
        repository.recover_interrupted(
            batch_id=batch.batch_id,
            phase=SyncItemAttemptPhase.QUOTE,
            before=_NOW.replace(second=30),
            finished_at=_NOW.replace(second=31),
        )
    assert repository.list_for_batch(batch.batch_id) == [first, second]


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row-lock race requires PostgreSQL")
def test_concurrent_normal_claim_has_one_lease_and_one_in_progress_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the unique run identity race with two independent PostgreSQL connections."""

    snapshot_repository, request, _content = _persisted_capture_inputs(monkeypatch)
    repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    invocation = InstrumentReferenceCaptureInvocation(request)
    barrier = Barrier(2)

    def claim_in_thread() -> InstrumentReferenceCaptureClaimResult:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return repository.claim(invocation)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim_in_thread) for _ in range(2)]
        results = [future.result(timeout=60) for future in futures]

    assert sorted(result.disposition.value for result in results) == [
        CaptureClaimDisposition.ACQUIRED.value,
        CaptureClaimDisposition.IN_PROGRESS.value,
    ]
    leases = [result.lease for result in results if result.lease is not None]
    assert len(leases) == 1
    lease = leases[0]
    assert lease is not None
    assert SyncRunModel.objects.filter(run_id=request.identity.run_id).count() == 1
    assert SyncBatchModel.objects.filter(batch_id=request.identity.batch_id).count() == 1
    assert repository.is_current(lease)


@pytest.mark.skipif(connection.vendor != "postgresql", reason="row-lock race requires PostgreSQL")
def test_claim_rechecks_run_parent_after_concurrent_first_claim_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve a committed first claim instead of misclassifying its children as orphaned."""

    snapshot_repository, request, _content = _persisted_capture_inputs(monkeypatch)
    winner_repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    waiting_repository = DjangoInstrumentReferenceCaptureClaimRepository(
        snapshot_repository, clock=lambda: _NOW
    )
    invocation = InstrumentReferenceCaptureInvocation(request)
    reached_orphan_check = Event()
    continue_orphan_check = Event()
    original_reject = waiting_repository._reject_orphaned_identity

    def pause_before_orphan_check(
        observed_request: InstrumentReferenceCaptureRequest,
    ) -> None:
        """Hold the losing claim after its initial missing-parent read."""

        reached_orphan_check.set()
        if not continue_orphan_check.wait(timeout=10):
            raise TimeoutError("timed out waiting to resume the losing claim")
        original_reject(observed_request)

    monkeypatch.setattr(waiting_repository, "_reject_orphaned_identity", pause_before_orphan_check)

    def claim_on_independent_connection() -> InstrumentReferenceCaptureClaimResult:
        """Run the paused claimant with its own PostgreSQL connection."""

        close_old_connections()
        try:
            return waiting_repository.claim(invocation)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting_future = executor.submit(claim_on_independent_connection)
        assert reached_orphan_check.wait(timeout=10)
        try:
            winner = winner_repository.claim(invocation)
        finally:
            continue_orphan_check.set()
        waiting = waiting_future.result(timeout=60)

    assert winner.disposition is CaptureClaimDisposition.ACQUIRED
    assert winner.lease is not None
    assert waiting.disposition is CaptureClaimDisposition.IN_PROGRESS
    assert waiting.lease is None
    assert SyncRunModel.objects.filter(run_id=request.identity.run_id).count() == 1
    assert SyncBatchModel.objects.filter(batch_id=request.identity.batch_id).count() == 1
    assert winner_repository.is_current(winner.lease)
