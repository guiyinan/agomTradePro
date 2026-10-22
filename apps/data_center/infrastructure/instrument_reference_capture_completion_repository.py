"""Fenced snapshot finalization over the existing capture claim/control rows."""

from __future__ import annotations

from datetime import UTC, datetime

from django.db import DEFAULT_DB_ALIAS, IntegrityError, transaction

from apps.data_center.application.instrument_reference_capture import (
    CaptureClaimDisposition,
    CaptureInvocationMode,
    InstrumentReferenceCaptureClaimResult,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureLease,
)
from apps.data_center.domain.control_plane import SyncItemState, SyncRunStatus
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimHistory,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
)
from apps.data_center.infrastructure.instrument_reference_capture_claim_repository import (
    DjangoInstrumentReferenceCaptureClaimRepository,
)
from apps.data_center.infrastructure.instrument_reference_capture_receipt import (
    _COMPLETION_CURSOR_NAME,
    CaptureCompletionMarker,
    validate_progress_checkpoints,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    InstrumentReferenceSnapshotPersistenceError,
)
from apps.data_center.infrastructure.models import (
    InstrumentReferenceSnapshotModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)

_PROGRESS_PREFIX = "ircap.v1.scope."


class DjangoInstrumentReferenceCaptureCompletionRepository(
    DjangoInstrumentReferenceCaptureClaimRepository
):
    """Acquire leases and atomically finalize snapshot plus receipt markers."""

    def claim(
        self,
        invocation: InstrumentReferenceCaptureInvocation,
    ) -> InstrumentReferenceCaptureClaimResult:
        """Acquire/resume a lease or replay only a matching sealed completion."""

        if type(invocation) is not InstrumentReferenceCaptureInvocation:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID"
            )
        request = invocation.request
        self._validate_request_mapping(request)
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            run = (
                SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(run_id=request.identity.run_id)
                .first()
            )
            if run is None:
                self._reject_orphaned_identity(request)
                return self._create_first_claim(invocation)
            batch = self._lock_exact_batch(request)
            checkpoints = self._lock_capture_checkpoints(request)
            history, pointers, marker = self._capture_context(request, checkpoints)
            self._validate_no_capture_attempts(request.identity)
            snapshots = self._snapshot_rows(request.identity.run_id)
            if marker is not None or snapshots:
                snapshot = self._read_completed_snapshot(
                    request,
                    run,
                    batch,
                    history,
                    pointers,
                    marker,
                    snapshots,
                )
                return InstrumentReferenceCaptureClaimResult(
                    CaptureClaimDisposition.COMPLETED,
                    request.identity,
                    request.request_sha256,
                    snapshot=snapshot,
                )
            self._validate_control_rows(request, run, batch)
            if invocation.mode is CaptureInvocationMode.NORMAL:
                return InstrumentReferenceCaptureClaimResult(
                    CaptureClaimDisposition.IN_PROGRESS,
                    request.identity,
                    request.request_sha256,
                )
            return self._append_resume_epoch(request, history)

    def is_current(self, lease: InstrumentReferenceCaptureLease) -> bool:
        """Check the exact latest epoch, returning false after completion."""

        if type(lease) is not InstrumentReferenceCaptureLease:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID"
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            run = (
                SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(run_id=lease.identity.run_id)
                .first()
            )
            if run is None:
                return False
            batch = self._lock_identity_batch(lease.identity)
            request = self._request_from_checkpoint_rows(lease)
            if request.identity != lease.identity or request.request_sha256 != lease.request_sha256:
                return False
            checkpoints = self._lock_capture_checkpoints(request)
            history, pointers, marker = self._capture_context(request, checkpoints)
            self._validate_no_capture_attempts(lease.identity)
            snapshots = self._snapshot_rows(request.identity.run_id)
            if marker is not None or snapshots:
                self._read_completed_snapshot(
                    request,
                    run,
                    batch,
                    history,
                    pointers,
                    marker,
                    snapshots,
                )
                return False
            self._validate_control_rows(request, run, batch)
            latest = history.latest
            return (
                latest is not None
                and latest == lease.epoch
                and lease.owner_capability.matches_digest(latest.owner_token_sha256)
            )

    def request_for_lease(
        self,
        lease: InstrumentReferenceCaptureLease,
    ) -> InstrumentReferenceCaptureRequest:
        """Rebuild the immutable request descriptor through locked checkpoints."""

        if type(lease) is not InstrumentReferenceCaptureLease:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID"
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            run = (
                SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(run_id=lease.identity.run_id)
                .first()
            )
            if run is None:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
                )
            self._lock_identity_batch(lease.identity)
            request = self._request_from_checkpoint_rows(lease)
            if request.identity != lease.identity or request.request_sha256 != lease.request_sha256:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
                )
            return request

    def complete_snapshot(
        self,
        lease: InstrumentReferenceCaptureLease,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Write snapshot, completion checkpoint and terminal run/batch atomically."""

        if (
            type(lease) is not InstrumentReferenceCaptureLease
            or type(content) is not InstrumentReferenceSnapshotContent
            or content.run_id != lease.identity.run_id
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_CONTENT_INVALID"
            )
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            run = (
                SyncRunModel._default_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(run_id=lease.identity.run_id)
                .first()
            )
            if run is None:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
                )
            batch = self._lock_identity_batch(lease.identity)
            request = self._request_from_checkpoint_rows(lease)
            if request.identity != lease.identity or request.request_sha256 != lease.request_sha256:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
                )
            checkpoints = self._lock_capture_checkpoints(request)
            history, pointers, marker = self._capture_context(request, checkpoints)
            self._validate_no_capture_attempts(lease.identity)
            snapshots = self._snapshot_rows(lease.identity.run_id)
            if marker is not None or snapshots:
                existing = self._read_completed_snapshot(
                    request,
                    run,
                    batch,
                    history,
                    pointers,
                    marker,
                    snapshots,
                )
                latest = history.latest
                if (
                    latest != lease.epoch
                    or latest is None
                    or not lease.owner_capability.matches_digest(latest.owner_token_sha256)
                ):
                    raise InstrumentReferenceCaptureContractError(
                        "INSTRUMENT_REFERENCE_CAPTURE_LEASE_STALE"
                    )
                if existing.content != content:
                    raise InstrumentReferenceCaptureContractError(
                        "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_CONTENT_MISMATCH"
                    )
                return existing
            self._validate_control_rows(request, run, batch)
            self._require_current_history(history, lease)
            self._validate_completion_content(request, content, pointers)
            snapshot = self._snapshot_repository.save_snapshot(content)
            marker_value = CaptureCompletionMarker(
                request_sha256=request.request_sha256,
                epoch=lease.epoch.epoch,
                claim_sha256=lease.epoch.claim_sha256,
                snapshot_id=snapshot.snapshot_id,
                snapshot_content_hash=snapshot.content_hash,
                snapshot_record_digest=snapshot.record_digest,
            )
            finished_at = max(self._completion_time(), snapshot.recorded_at)
            try:
                SyncCheckpointModel._default_manager.using(DEFAULT_DB_ALIAS).create(
                    run_id=request.identity.run_id,
                    batch_id=request.identity.batch_id,
                    cursor_name=_COMPLETION_CURSOR_NAME,
                    cursor_value=marker_value.encode(),
                    state=SyncItemState.SUCCEEDED.value,
                    processed=0,
                    failed=0,
                    recorded_at=finished_at,
                    error_code="",
                )
            except IntegrityError as exc:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_CONFLICT"
                ) from exc
            scope_count = len(request.scopes)
            run.status = SyncRunStatus.STORED.value
            run.outcome = "success"
            run.fetched = scope_count
            run.validated = scope_count
            run.quarantined = 0
            run.succeeded = scope_count
            run.failed = 0
            run.stored = content.record_count
            run.published = 0
            run.unchanged = 0
            run.finished_at = finished_at
            run.save(
                using=DEFAULT_DB_ALIAS,
                update_fields=[
                    "status",
                    "outcome",
                    "fetched",
                    "validated",
                    "quarantined",
                    "succeeded",
                    "failed",
                    "stored",
                    "published",
                    "unchanged",
                    "finished_at",
                    "updated_at",
                ],
            )
            batch.state = SyncItemState.SUCCEEDED.value
            batch.fetched = scope_count
            batch.validated = scope_count
            batch.quarantined = 0
            batch.succeeded = scope_count
            batch.failed = 0
            batch.stored = content.record_count
            batch.published = 0
            batch.finished_at = finished_at
            batch.save(
                using=DEFAULT_DB_ALIAS,
                update_fields=[
                    "state",
                    "fetched",
                    "validated",
                    "quarantined",
                    "succeeded",
                    "failed",
                    "stored",
                    "published",
                    "finished_at",
                    "updated_at",
                ],
            )
            return snapshot

    def _validate_checkpoints(
        self,
        request: InstrumentReferenceCaptureRequest,
        rows: list[SyncCheckpointModel],
    ) -> CaptureClaimHistory:
        """Validate scope and completion receipts before the base claim chain."""

        ignored_rows = [
            row
            for row in rows
            if row.cursor_name.startswith(_PROGRESS_PREFIX)
            or row.cursor_name == _COMPLETION_CURSOR_NAME
        ]
        base_rows = [row for row in rows if row not in ignored_rows]
        history, _pointers, _marker = self._capture_context(
            request,
            rows,
            base_rows=base_rows,
        )
        return history

    def _capture_context(
        self,
        request: InstrumentReferenceCaptureRequest,
        rows: list[SyncCheckpointModel],
        *,
        base_rows: list[SyncCheckpointModel] | None = None,
    ) -> tuple[
        CaptureClaimHistory,
        dict[tuple[InstrumentReferenceCaptureScope, str], str],
        CaptureCompletionMarker | None,
    ]:
        """Return the claim chain, exact per-scope pointers and optional final marker."""

        if base_rows is None:
            base_rows = [
                row
                for row in rows
                if not row.cursor_name.startswith(_PROGRESS_PREFIX)
                and row.cursor_name != _COMPLETION_CURSOR_NAME
            ]
        history = super()._validate_checkpoints(request, base_rows)
        progress_values = [
            (row.cursor_name, row.cursor_value)
            for row in rows
            if row.cursor_name.startswith(_PROGRESS_PREFIX)
        ]
        pointers = validate_progress_checkpoints(request, progress_values)
        completion_rows = [row for row in rows if row.cursor_name == _COMPLETION_CURSOR_NAME]
        if len(completion_rows) > 1:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_DUPLICATE"
            )
        marker = (
            CaptureCompletionMarker.decode(completion_rows[0].cursor_value)
            if completion_rows
            else None
        )
        return history, pointers, marker

    def _read_completed_snapshot(
        self,
        request: InstrumentReferenceCaptureRequest,
        run: SyncRunModel,
        batch: SyncBatchModel,
        history: CaptureClaimHistory,
        pointers: dict[tuple[InstrumentReferenceCaptureScope, str], str],
        marker: CaptureCompletionMarker | None,
        snapshots: list[InstrumentReferenceSnapshotModel],
    ) -> InstrumentReferenceSnapshotRecord:
        """Require exactly one marker, snapshot, matching progress and terminal state."""

        if marker is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_MISSING"
            )
        if len(snapshots) != 1:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_SNAPSHOT_MISSING"
            )
        latest = history.latest
        snapshot_row = snapshots[0]
        if (
            latest is None
            or marker.request_sha256 != request.request_sha256
            or marker.epoch != latest.epoch
            or marker.claim_sha256 != latest.claim_sha256
            or marker.snapshot_id != snapshot_row.snapshot_id
            or marker.snapshot_content_hash != snapshot_row.content_hash
            or marker.snapshot_record_digest != snapshot_row.record_digest
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_MISMATCH"
            )
        try:
            snapshot = self._snapshot_repository.get_snapshot(marker.snapshot_id)
        except InstrumentReferenceSnapshotPersistenceError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_SNAPSHOT_INVALID"
            ) from exc
        if (
            type(snapshot) is not InstrumentReferenceSnapshotRecord
            or snapshot.snapshot_id != marker.snapshot_id
            or snapshot.content_hash != marker.snapshot_content_hash
            or snapshot.record_digest != marker.snapshot_record_digest
            or not self._completion_content_matches(request, snapshot.content, pointers)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETION_MARKER_MISMATCH"
            )
        self._validate_completed_control_rows(request, run, batch, snapshot)
        return snapshot

    def _validate_completion_content(
        self,
        request: InstrumentReferenceCaptureRequest,
        content: InstrumentReferenceSnapshotContent,
        pointers: dict[tuple[InstrumentReferenceCaptureScope, str], str],
    ) -> None:
        """Reject partial, cross-request or non-source-only snapshots before insert."""

        if not self._completion_content_matches(request, content, pointers):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_CONTENT_INVALID"
            )

    @staticmethod
    def _completion_content_matches(
        request: InstrumentReferenceCaptureRequest,
        content: InstrumentReferenceSnapshotContent,
        pointers: dict[tuple[InstrumentReferenceCaptureScope, str], str],
    ) -> bool:
        """Bind every requested scope to its one occurrence and both progress pointers."""

        if (
            type(content) is not InstrumentReferenceSnapshotContent
            or content.run_id != request.identity.run_id
            or content.mapping_record != request.mapping_record
            or content.source_observed_at is not None
            or content.source_available_at is not None
            or content.must_not_use_for_decision is not True
            or content.must_not_execute is not True
            or len(content.fetch_rounds) != 1
        ):
            return False
        fetch_round = content.fetch_rounds[0]
        if (
            type(fetch_round) is not InstrumentReferenceFetchRound
            or fetch_round.fetch_round_id != request.identity.capture_id
            or type(fetch_round.candidate) is not InstrumentReferenceCandidate
        ):
            return False
        candidate = fetch_round.candidate
        if (
            candidate.provider_contract != request.provider_contract
            or candidate.crosswalk != request.mapping_record.content.source_crosswalk
            or tuple((item.exchange, item.list_status) for item in candidate.occurrences)
            != tuple((item.exchange, item.list_status) for item in request.scopes)
        ):
            return False
        for scope, occurrence in zip(request.scopes, candidate.occurrences, strict=True):
            if (
                occurrence.occurrence_id != request.occurrence_id(scope)
                or occurrence.raw_audit_reference.run_id != str(request.identity.run_id)
                or occurrence.raw_audit_reference.ingested_run_id != str(request.identity.batch_id)
                or pointers.get((scope, "response")) != occurrence.raw_payload_id
                or pointers.get((scope, "audit")) != occurrence.raw_audit_reference.raw_audit_id
            ):
                return False
        return True

    @staticmethod
    def _require_current_history(
        history: CaptureClaimHistory,
        lease: InstrumentReferenceCaptureLease,
    ) -> None:
        """Reject a lease whose epoch was replaced by a later resume claim."""

        latest = history.latest
        if (
            latest is None
            or latest != lease.epoch
            or not lease.owner_capability.matches_digest(latest.owner_token_sha256)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_STALE"
            )

    @staticmethod
    def _validate_completed_control_rows(
        request: InstrumentReferenceCaptureRequest,
        run: SyncRunModel,
        batch: SyncBatchModel,
        snapshot: InstrumentReferenceSnapshotRecord,
    ) -> None:
        """Require exact successful terminal states and counters for this snapshot."""

        scope_count = len(request.scopes)
        expected_run_counts = (
            scope_count,
            scope_count,
            scope_count,
            0,
            scope_count,
            0,
            snapshot.content.record_count,
            0,
            0,
        )
        expected_batch_counts = expected_run_counts[:-1]
        finished_at = run.finished_at
        if (
            run.run_id != request.identity.run_id
            or run.dataset_key != request.provider_contract.dataset_key
            or run.trigger != "instrument_reference_capture"
            or run.provider_name != request.provider_contract.provider_name
            or run.contract_version != request.provider_contract.contract_version
            or run.config_snapshot_hash != ""
            or run.status != SyncRunStatus.STORED.value
            or run.outcome != "success"
            or run.finished_at is None
            or run.error_code
            or run.error_message
            or (
                run.requested,
                run.fetched,
                run.validated,
                run.quarantined,
                run.succeeded,
                run.failed,
                run.stored,
                run.published,
                run.unchanged,
            )
            != expected_run_counts
            or batch.batch_id != request.identity.batch_id
            or batch.run_id != request.identity.run_id
            or batch.dataset_key != request.provider_contract.dataset_key
            or batch.provider_name != request.provider_contract.provider_name
            or batch.idempotency_key != request.identity.idempotency_key
            or batch.state != SyncItemState.SUCCEEDED.value
            or batch.finished_at != finished_at
            or batch.error_code
            or batch.error_message
            or batch.window_start is not None
            or batch.window_end is not None
            or (
                batch.requested,
                batch.fetched,
                batch.validated,
                batch.quarantined,
                batch.succeeded,
                batch.failed,
                batch.stored,
                batch.published,
            )
            != expected_batch_counts
            or type(finished_at) is not datetime
            or finished_at.tzinfo is None
            or finished_at.utcoffset() is None
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_COMPLETED_CONTROL_PLANE_INVALID"
            )

    def _completion_time(self) -> datetime:
        """Return repository-owned aware UTC completion metadata."""

        value = self._now()
        if value.utcoffset() != UTC.utcoffset(value):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLOCK_INVALID"
            )
        return value


__all__ = ["DjangoInstrumentReferenceCaptureCompletionRepository"]
