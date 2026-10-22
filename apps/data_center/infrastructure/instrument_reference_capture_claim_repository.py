"""Persist fenced claims for source-only instrument-reference captures."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from django.db import DEFAULT_DB_ALIAS, IntegrityError, router, transaction
from django.db.models import Q
from django.utils import timezone

from apps.data_center.application.instrument_reference_capture import (
    CaptureClaimDisposition,
    CaptureInvocationMode,
    InstrumentReferenceCaptureClaimPort,
    InstrumentReferenceCaptureClaimResult,
    InstrumentReferenceCaptureInvocation,
    InstrumentReferenceCaptureLease,
)
from apps.data_center.application.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotRepositoryPort,
)
from apps.data_center.domain.control_plane import SyncItemState, SyncRunStatus
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureClaimHistory,
    CaptureClaimMarker,
    CaptureClaimPayload,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureIdentity,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingRecord,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    InstrumentReferenceSnapshotPersistenceError,
)

from .instrument_reference_capture_descriptor_codec import (
    _REQUEST_PREFIX,
    _int_payload,
    _join_request_descriptor,
    _mapping_value,
    _parse_canonical_request,
    _provider_contract_from_payload,
    _request_descriptor_chunks,
    _string_payload,
    _uuid_payload,
)
from .instrument_reference_capture_write_guard import (
    CAPTURE_CHECKPOINT_PREFIX as _CHECKPOINT_PREFIX,
)
from .instrument_reference_capture_write_guard import CAPTURE_TRIGGER as _CAPTURE_TRIGGER
from .models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncItemAttemptModel,
    SyncRunModel,
)


class _DefaultSnapshotRepository(InstrumentReferenceSnapshotRepositoryPort, Protocol):
    """Require snapshot reads to share the capture control plane's default alias."""

    @property
    def unit_of_work_key(self) -> str:
        """Identify the exact alias used for immutable source-evidence reads."""


class DjangoInstrumentReferenceCaptureClaimRepository(InstrumentReferenceCaptureClaimPort):
    """Claim one capture identity, append resume epochs, and reject unfenced snapshots."""

    def __init__(
        self,
        snapshot_repository: _DefaultSnapshotRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Inject the existing sealed-snapshot reader and an optional repository clock."""

        if snapshot_repository.unit_of_work_key != "django:default":
            raise ValueError("capture claims require the default snapshot database alias")
        self._snapshot_repository = snapshot_repository
        self._clock = clock or timezone.now
        self._using = DEFAULT_DB_ALIAS
        for model in (
            SyncRunModel,
            SyncBatchModel,
            SyncCheckpointModel,
            SyncItemAttemptModel,
            InstrumentReferenceMappingModel,
            InstrumentReferenceSnapshotModel,
        ):
            for alias in (router.db_for_read(model), router.db_for_write(model)):
                if alias is not None and alias != self._using:
                    raise ValueError("capture claims require one default database alias")

    def claim(
        self,
        invocation: InstrumentReferenceCaptureInvocation,
    ) -> InstrumentReferenceCaptureClaimResult:
        """Acquire or resume a fenced lease, or report an existing owner."""

        if type(invocation) is not InstrumentReferenceCaptureInvocation:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_INVOCATION_INVALID"
            )
        request = invocation.request
        self._validate_request_mapping(request)
        identity = request.identity
        with transaction.atomic(using=self._using):
            run = (
                SyncRunModel._default_manager.using(self._using)
                .select_for_update()
                .filter(run_id=identity.run_id)
                .first()
            )
            if run is None:
                self._reject_orphaned_identity(request)
                return self._create_first_claim(invocation)
            batch = self._lock_exact_batch(request)
            checkpoints = self._lock_capture_checkpoints(request)
            self._validate_control_rows(request, run, batch)
            history = self._validate_checkpoints(request, checkpoints)
            self._validate_no_capture_attempts(identity)
            if self._snapshot_rows(identity.run_id):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_INVALID"
                )
            if invocation.mode is CaptureInvocationMode.NORMAL:
                return InstrumentReferenceCaptureClaimResult(
                    CaptureClaimDisposition.IN_PROGRESS,
                    identity,
                    request.request_sha256,
                )
            return self._append_resume_epoch(request, history)

    def is_current(self, lease: InstrumentReferenceCaptureLease) -> bool:
        """Return whether the exact in-memory capability owns the latest durable epoch."""

        if type(lease) is not InstrumentReferenceCaptureLease:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_LEASE_INVALID"
            )
        with transaction.atomic(using=self._using):
            run = (
                SyncRunModel._default_manager.using(self._using)
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
            self._validate_control_rows(request, run, batch)
            history = self._validate_checkpoints(request, checkpoints)
            self._validate_no_capture_attempts(lease.identity)
            if self._snapshot_rows(request.identity.run_id):
                return False
            latest = history.latest
            return (
                latest is not None
                and latest == lease.epoch
                and lease.owner_capability.matches_digest(latest.owner_token_sha256)
            )

    def _validate_request_mapping(self, request: InstrumentReferenceCaptureRequest) -> None:
        """Require the exact requested append-only mapping to remain readable."""

        if type(request) is not InstrumentReferenceCaptureRequest:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
            )
        try:
            persisted = self._snapshot_repository.get_mapping(
                request.mapping_record.mapping_record_id
            )
        except InstrumentReferenceSnapshotPersistenceError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_INVALID"
            ) from exc
        if type(persisted) is not InstrumentReferenceMappingRecord:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_NOT_PERSISTED"
            )
        if persisted != request.mapping_record:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_MISMATCH"
            )

    def _create_first_claim(
        self,
        invocation: InstrumentReferenceCaptureInvocation,
    ) -> InstrumentReferenceCaptureClaimResult:
        """Insert a complete first claim in one savepoint and resolve uniqueness races."""

        request = invocation.request
        identity = request.identity
        capability = CaptureOwnerCapability.generate()
        epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
        now = self._now()
        try:
            with transaction.atomic(using=self._using):
                SyncRunModel._default_manager.using(self._using).create(
                    run_id=identity.run_id,
                    dataset_key=request.provider_contract.dataset_key,
                    trigger=_CAPTURE_TRIGGER,
                    status=SyncRunStatus.FETCHING.value,
                    outcome="blocked",
                    provider_name=request.provider_contract.provider_name,
                    contract_version=request.provider_contract.contract_version,
                    config_snapshot_hash="",
                    requested=len(request.scopes),
                    started_at=now,
                )
                SyncBatchModel._default_manager.using(self._using).create(
                    batch_id=identity.batch_id,
                    run_id=identity.run_id,
                    dataset_key=request.provider_contract.dataset_key,
                    provider_name=request.provider_contract.provider_name,
                    idempotency_key=identity.idempotency_key,
                    state=SyncItemState.RUNNING.value,
                    requested=len(request.scopes),
                    started_at=now,
                )
                self._insert_request_descriptor(request, now)
                self._insert_claim_epoch(request, epoch, now)
                persisted_run = (
                    SyncRunModel._default_manager.using(self._using)
                    .select_for_update()
                    .get(run_id=identity.run_id)
                )
                persisted_batch = self._lock_exact_batch(request)
                persisted_checkpoints = self._lock_capture_checkpoints(request)
                self._validate_control_rows(request, persisted_run, persisted_batch)
                self._validate_checkpoints(request, persisted_checkpoints)
                if self._snapshot_rows(identity.run_id):
                    raise InstrumentReferenceCaptureContractError(
                        "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_INVALID"
                    )
                self._validate_no_capture_attempts(identity)
        except IntegrityError:
            winner = (
                SyncRunModel._default_manager.using(self._using)
                .select_for_update()
                .filter(run_id=identity.run_id)
                .first()
            )
            if winner is None:
                self._reject_orphaned_identity(request)
                raise
            batch = self._lock_exact_batch(request)
            checkpoints = self._lock_capture_checkpoints(request)
            self._validate_control_rows(request, winner, batch)
            self._validate_checkpoints(request, checkpoints)
            self._validate_no_capture_attempts(identity)
            if self._snapshot_rows(identity.run_id):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_SNAPSHOT_INVALID"
                ) from None
            return InstrumentReferenceCaptureClaimResult(
                CaptureClaimDisposition.IN_PROGRESS,
                identity,
                request.request_sha256,
            )
        return InstrumentReferenceCaptureClaimResult(
            CaptureClaimDisposition.ACQUIRED,
            identity,
            request.request_sha256,
            lease=InstrumentReferenceCaptureLease(
                identity=identity,
                request_sha256=request.request_sha256,
                epoch=epoch,
                owner_capability=capability,
            ),
        )

    def _append_resume_epoch(
        self,
        request: InstrumentReferenceCaptureRequest,
        history: CaptureClaimHistory,
    ) -> InstrumentReferenceCaptureClaimResult:
        """Append one strictly chained epoch and replace the prior in-memory owner."""

        capability = CaptureOwnerCapability.generate()
        previous = history.latest
        epoch = CaptureClaimEpoch.issue(
            history.next_epoch,
            request.request_sha256,
            previous.claim_sha256 if previous is not None else None,
            capability,
        )
        self._insert_claim_epoch(request, epoch, self._now())
        return InstrumentReferenceCaptureClaimResult(
            CaptureClaimDisposition.ACQUIRED,
            request.identity,
            request.request_sha256,
            lease=InstrumentReferenceCaptureLease(
                identity=request.identity,
                request_sha256=request.request_sha256,
                epoch=epoch,
                owner_capability=capability,
            ),
        )

    def _lock_exact_batch(
        self,
        request: InstrumentReferenceCaptureRequest,
    ) -> SyncBatchModel:
        """Lock and validate the batch belonging to one exact request."""

        return self._lock_identity_batch(request.identity)

    def _lock_identity_batch(
        self,
        identity: InstrumentReferenceCaptureIdentity,
    ) -> SyncBatchModel:
        """Lock an exact deterministic batch after its run parent is already locked."""

        batch = (
            SyncBatchModel._default_manager.using(self._using)
            .select_for_update()
            .filter(batch_id=identity.batch_id)
            .first()
        )
        rows = list(
            SyncBatchModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                Q(run_id=identity.run_id)
                | Q(batch_id=identity.batch_id)
                | Q(idempotency_key=identity.idempotency_key)
            )
            .order_by("batch_id")
        )
        if (
            batch is None
            or len(rows) != 1
            or rows[0].batch_id != batch.batch_id
            or batch.run_id != identity.run_id
            or batch.idempotency_key != identity.idempotency_key
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
            )
        return batch

    def _lock_capture_checkpoints(
        self,
        request: InstrumentReferenceCaptureRequest,
    ) -> list[SyncCheckpointModel]:
        """Lock every checkpoint touching the capture run or batch in stable order."""

        identity = request.identity
        rows = list(
            SyncCheckpointModel._default_manager.using(self._using)
            .select_for_update()
            .filter(Q(run_id=identity.run_id) | Q(batch_id=identity.batch_id))
            .order_by("cursor_name", "checkpoint_id")
        )
        self._validate_checkpoint_row_envelopes(rows, identity.run_id, identity.batch_id)
        return rows

    def _validate_checkpoint_row_envelopes(
        self,
        rows: list[SyncCheckpointModel],
        run_id: UUID,
        batch_id: UUID,
    ) -> None:
        """Validate immutable checkpoint metadata as well as its descriptor value."""

        for row in rows:
            recorded_at = row.recorded_at
            if (
                row.run_id != run_id
                or row.batch_id != batch_id
                or type(row.cursor_name) is not str
                or not row.cursor_name.startswith(_CHECKPOINT_PREFIX)
                or row.state != SyncItemState.SUCCEEDED.value
                or row.processed != 0
                or row.failed != 0
                or row.error_code != ""
                or type(recorded_at) is not datetime
                or recorded_at.tzinfo is None
                or recorded_at.utcoffset() is None
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
                )

    def _validate_control_rows(
        self,
        request: InstrumentReferenceCaptureRequest,
        run: SyncRunModel,
        batch: SyncBatchModel,
    ) -> None:
        """Compare all stable run/batch identity and untouched accounting fields."""

        contract = request.provider_contract
        identity = request.identity
        run_counts = (
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
        batch_counts = (
            batch.requested,
            batch.fetched,
            batch.validated,
            batch.quarantined,
            batch.succeeded,
            batch.failed,
            batch.stored,
            batch.published,
        )
        if (
            run.run_id != identity.run_id
            or run.dataset_key != contract.dataset_key
            or run.trigger != _CAPTURE_TRIGGER
            or run.provider_name != contract.provider_name
            or run.contract_version != contract.contract_version
            or run.config_snapshot_hash != ""
            or run.status != SyncRunStatus.FETCHING.value
            or run.outcome != "blocked"
            or run.finished_at is not None
            or run.error_code
            or run.error_message
            or run_counts != (len(request.scopes), 0, 0, 0, 0, 0, 0, 0, 0)
            or batch.batch_id != identity.batch_id
            or batch.run_id != identity.run_id
            or batch.dataset_key != contract.dataset_key
            or batch.provider_name != contract.provider_name
            or batch.idempotency_key != identity.idempotency_key
            or batch.state != SyncItemState.RUNNING.value
            or batch.finished_at is not None
            or batch.error_code
            or batch.error_message
            or batch.window_start is not None
            or batch.window_end is not None
            or batch_counts != (len(request.scopes), 0, 0, 0, 0, 0, 0, 0)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
            )

    def _validate_checkpoints(
        self,
        request: InstrumentReferenceCaptureRequest,
        rows: list[SyncCheckpointModel],
    ) -> CaptureClaimHistory:
        """Verify exact request chunks and the complete contiguous claim epoch chain."""

        descriptor_rows: list[SyncCheckpointModel] = []
        marker_rows: list[tuple[object, object]] = []
        payload_rows: list[tuple[object, object]] = []
        for row in rows:
            if row.cursor_name.startswith(_REQUEST_PREFIX):
                descriptor_rows.append(row)
            elif row.cursor_name.startswith("ircap.v1.claim.marker."):
                marker_rows.append((row.cursor_name, row.cursor_value))
            elif row.cursor_name.startswith("ircap.v1.claim.payload."):
                payload_rows.append((row.cursor_name, row.cursor_value))
            else:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_INVALID"
                )
        descriptor = _join_request_descriptor(descriptor_rows)
        if (
            descriptor != request.canonical_request
            or hashlib.sha256(descriptor.encode("ascii")).hexdigest() != request.request_sha256
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
            )
        history = CaptureClaimHistory.from_checkpoint_rows(
            request.request_sha256,
            tuple(marker_rows),
            tuple(payload_rows),
        )
        if history.latest is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID"
            )
        return history

    def _validate_no_capture_attempts(
        self,
        identity: InstrumentReferenceCaptureIdentity,
    ) -> None:
        """Reject item-attempt rows because source captures never use the generic ledger."""

        if (
            SyncItemAttemptModel._default_manager.using(self._using)
            .filter(Q(run_id=identity.run_id) | Q(batch_id=identity.batch_id))
            .exists()
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
            )

    def _snapshot_rows(self, run_id: UUID) -> list[InstrumentReferenceSnapshotModel]:
        """Read every sealed snapshot row linked to one capture run."""

        return list(
            InstrumentReferenceSnapshotModel._default_manager.using(self._using)
            .filter(run_id=run_id)
            .order_by("snapshot_id")
        )

    def _reject_orphaned_identity(self, request: InstrumentReferenceCaptureRequest) -> None:
        """Fail closed when identity rows remain without a committed run parent."""

        identity = request.identity
        has_identity_rows = (
            SyncBatchModel._default_manager.using(self._using)
            .filter(
                Q(run_id=identity.run_id)
                | Q(batch_id=identity.batch_id)
                | Q(idempotency_key=identity.idempotency_key)
            )
            .exists()
            or SyncCheckpointModel._default_manager.using(self._using)
            .filter(Q(run_id=identity.run_id) | Q(batch_id=identity.batch_id))
            .exists()
            or SyncItemAttemptModel._default_manager.using(self._using)
            .filter(Q(run_id=identity.run_id) | Q(batch_id=identity.batch_id))
            .exists()
            or InstrumentReferenceSnapshotModel._default_manager.using(self._using)
            .filter(run_id=identity.run_id)
            .exists()
        )
        if not has_identity_rows:
            return
        run = (
            SyncRunModel._default_manager.using(self._using)
            .select_for_update()
            .filter(run_id=identity.run_id)
            .first()
        )
        if run is not None:
            return
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_INVALID"
        )

    def _insert_request_descriptor(
        self,
        request: InstrumentReferenceCaptureRequest,
        recorded_at: datetime,
    ) -> None:
        """Persist a complete canonical request descriptor in bounded fixed-index chunks."""

        chunks = _request_descriptor_chunks(request.canonical_request)
        self._insert_checkpoints(
            request,
            tuple((name, value) for name, value in chunks),
            recorded_at,
        )

    def _insert_claim_epoch(
        self,
        request: InstrumentReferenceCaptureRequest,
        epoch: CaptureClaimEpoch,
        recorded_at: datetime,
    ) -> None:
        """Append the immutable marker and payload rows for exactly one claim epoch."""

        marker = CaptureClaimMarker.for_epoch(epoch.epoch)
        payload = CaptureClaimPayload.for_claim(epoch)
        self._insert_checkpoints(
            request,
            (
                (marker.cursor_name, marker.cursor_value),
                (payload.cursor_name, payload.cursor_value),
            ),
            recorded_at,
        )

    def _insert_checkpoints(
        self,
        request: InstrumentReferenceCaptureRequest,
        values: tuple[tuple[str, str], ...],
        recorded_at: datetime,
    ) -> None:
        """Insert reserved checkpoint values as append-only rows in the active transaction."""

        models_to_create = [
            SyncCheckpointModel(
                checkpoint_id=uuid4(),
                run_id=request.identity.run_id,
                batch_id=request.identity.batch_id,
                cursor_name=name,
                cursor_value=value,
                state=SyncItemState.SUCCEEDED.value,
                processed=0,
                failed=0,
                recorded_at=recorded_at,
                error_code="",
            )
            for name, value in values
        ]
        SyncCheckpointModel._default_manager.using(self._using).bulk_create(
            models_to_create,
            batch_size=100,
        )

    def _request_from_checkpoint_rows(
        self,
        lease: InstrumentReferenceCaptureLease,
    ) -> InstrumentReferenceCaptureRequest:
        """Rebuild the exact canonical request needed to validate a persisted lease."""

        identity = lease.identity
        rows = list(
            SyncCheckpointModel._default_manager.using(self._using)
            .select_for_update()
            .filter(Q(run_id=identity.run_id) | Q(batch_id=identity.batch_id))
            .order_by("cursor_name", "checkpoint_id")
        )
        self._validate_checkpoint_row_envelopes(rows, identity.run_id, identity.batch_id)
        descriptor_rows = [row for row in rows if row.cursor_name.startswith(_REQUEST_PREFIX)]
        descriptor = _join_request_descriptor(descriptor_rows)
        if hashlib.sha256(descriptor.encode("ascii")).hexdigest() != lease.request_sha256:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
            )
        payload = _parse_canonical_request(descriptor)
        if payload.get("capture_id") != str(identity.capture_id):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_IDENTITY_INVALID"
            )
        contract_payload = _mapping_value(payload, "provider_contract")
        contract = _provider_contract_from_payload(contract_payload)
        mapping_payload = _mapping_value(payload, "mapping")
        mapping_id = _uuid_payload(mapping_payload, "mapping_record_id")
        try:
            mapping_record = self._snapshot_repository.get_mapping(mapping_id)
        except InstrumentReferenceSnapshotPersistenceError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_INVALID"
            ) from exc
        if (
            type(mapping_record) is not InstrumentReferenceMappingRecord
            or mapping_record.content_hash
            != _string_payload(mapping_payload, "mapping_content_hash")
            or mapping_record.record_digest
            != _string_payload(mapping_payload, "mapping_record_digest")
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_MISMATCH"
            )
        route_id = _string_payload(payload, "provider_route_id")
        route_revision = _string_payload(payload, "provider_route_revision")
        provider_configuration_id = _int_payload(payload, "provider_configuration_id")
        actor = payload.get("actor_provenance")
        if actor is not None and type(actor) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
            )
        source_only = payload.get("source_only")
        alias = payload.get("repository_alias")
        if source_only is not True or alias != "default":
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_INVALID"
            )
        request = InstrumentReferenceCaptureRequest(
            capture_id=identity.capture_id,
            provider_contract=contract,
            provider_route_id=route_id,
            provider_route_revision=route_revision,
            provider_configuration_id=provider_configuration_id,
            mapping_record=mapping_record,
            actor_provenance=actor,
            source_only=True,
            repository_alias="default",
        )
        if (
            request.canonical_request != descriptor
            or request.request_sha256 != lease.request_sha256
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_NONCANONICAL"
            )
        return request

    def _now(self) -> datetime:
        """Return one exact aware repository timestamp for new durable claim rows."""

        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLOCK_INVALID"
            )
        return value


__all__ = ["DjangoInstrumentReferenceCaptureClaimRepository"]
