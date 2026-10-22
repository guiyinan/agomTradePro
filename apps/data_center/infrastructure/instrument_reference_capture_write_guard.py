"""Lock-order and namespace guards for source-capture-owned control-plane rows."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, transaction

from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
)

from .models import SyncBatchModel, SyncCheckpointModel, SyncRunModel

CAPTURE_TRIGGER = "instrument_reference_capture"
CAPTURE_IDEMPOTENCY_PREFIX = "instrument-reference-capture.v1:"
CAPTURE_CHECKPOINT_PREFIX = "ircap.v1."


def capture_run_is_reserved(run_id: UUID, *, using: str = DEFAULT_DB_ALIAS) -> bool:
    """Find durable capture evidence through every existing control-plane locator."""

    return (
        SyncRunModel._default_manager.using(using)
        .filter(run_id=run_id, trigger=CAPTURE_TRIGGER)
        .exists()
        or SyncBatchModel._default_manager.using(using)
        .filter(run_id=run_id, idempotency_key__startswith=CAPTURE_IDEMPOTENCY_PREFIX)
        .exists()
        or SyncCheckpointModel._default_manager.using(using)
        .filter(run_id=run_id, cursor_name__startswith=CAPTURE_CHECKPOINT_PREFIX)
        .exists()
    )


def capture_batch_is_reserved(batch_id: UUID, *, using: str = DEFAULT_DB_ALIAS) -> bool:
    """Find capture ownership by batch identity, parent run, key, or checkpoint prefix."""

    batch = (
        SyncBatchModel._default_manager.using(using)
        .filter(batch_id=batch_id)
        .values("run_id", "idempotency_key")
        .first()
    )
    if batch is None:
        return (
            SyncCheckpointModel._default_manager.using(using)
            .filter(
                batch_id=batch_id,
                cursor_name__startswith=CAPTURE_CHECKPOINT_PREFIX,
            )
            .exists()
        )
    run_id = batch["run_id"]
    idempotency_key = batch["idempotency_key"]
    if type(run_id) is not UUID or type(idempotency_key) is not str:
        return True
    return (
        idempotency_key.startswith(CAPTURE_IDEMPOTENCY_PREFIX)
        or capture_run_is_reserved(run_id, using=using)
        or (
            SyncCheckpointModel._default_manager.using(using)
            .filter(batch_id=batch_id, cursor_name__startswith=CAPTURE_CHECKPOINT_PREFIX)
            .exists()
        )
    )


def lock_run_rows(
    run_ids: Iterable[UUID],
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> dict[UUID, SyncRunModel]:
    """Lock existing parent runs in UUID order before any batch or attempt row."""

    normalized = tuple(sorted(set(run_ids), key=str))
    if not normalized:
        return {}
    return {
        row.run_id: row
        for row in (
            SyncRunModel._default_manager.using(using)
            .select_for_update()
            .filter(run_id__in=normalized)
            .order_by("run_id")
        )
    }


def lock_batch_rows(
    batch_ids: Iterable[UUID],
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> dict[UUID, SyncBatchModel]:
    """Lock existing batches in UUID order, always after their run parents."""

    normalized = tuple(sorted(set(batch_ids), key=str))
    if not normalized:
        return {}
    return {
        row.batch_id: row
        for row in (
            SyncBatchModel._default_manager.using(using)
            .select_for_update()
            .filter(batch_id__in=normalized)
            .order_by("batch_id")
        )
    }


def reject_reserved_write() -> None:
    """Raise the stable capture contract error for a generic control-plane writer."""

    raise InstrumentReferenceCaptureContractError(
        "INSTRUMENT_REFERENCE_CAPTURE_CONTROL_PLANE_RESERVED"
    )


def ensure_generic_run_write_allowed(run_id: UUID, trigger: str) -> None:
    """Reject incoming capture identities and any run already carrying capture evidence."""

    if trigger == CAPTURE_TRIGGER or capture_run_is_reserved(run_id):
        reject_reserved_write()


def ensure_generic_batch_write_allowed(
    *,
    batch_id: UUID,
    run_id: UUID,
    idempotency_key: str,
) -> None:
    """Reject both an existing captured batch and any request targeting its namespace."""

    if (
        idempotency_key.startswith(CAPTURE_IDEMPOTENCY_PREFIX)
        or capture_batch_is_reserved(batch_id)
        or capture_run_is_reserved(run_id)
    ):
        reject_reserved_write()


def ensure_generic_checkpoint_write_allowed(
    *,
    run_id: UUID,
    batch_id: UUID,
    cursor_name: str,
) -> None:
    """Reject reserved cursor names and checkpoints linked to any captured owner."""

    if (
        cursor_name.startswith(CAPTURE_CHECKPOINT_PREFIX)
        or capture_run_is_reserved(run_id)
        or capture_batch_is_reserved(batch_id)
    ):
        reject_reserved_write()


@contextmanager
def guarded_generic_batch_write(
    *,
    batch_id: UUID,
    run_id: UUID,
    idempotency_key: str,
) -> Iterator[None]:
    """Lock the full ordinary batch namespace before its upsert transaction."""

    if idempotency_key.startswith(CAPTURE_IDEMPOTENCY_PREFIX):
        reject_reserved_write()
    existing = (
        SyncBatchModel._default_manager.filter(idempotency_key=idempotency_key)
        .values("batch_id", "run_id")
        .first()
    )
    reused_id = (
        SyncBatchModel._default_manager.filter(batch_id=batch_id)
        .values("batch_id", "run_id")
        .first()
    )
    run_ids = {run_id}
    batch_ids = {batch_id}
    for probe in (existing, reused_id):
        if probe is None:
            continue
        probed_run_id = probe["run_id"]
        probed_batch_id = probe["batch_id"]
        if type(probed_run_id) is not UUID or type(probed_batch_id) is not UUID:
            raise ValueError("sync batch identity is invalid")
        run_ids.add(probed_run_id)
        batch_ids.add(probed_batch_id)
    with transaction.atomic():
        run_rows = lock_run_rows(run_ids)
        current_by_key = (
            SyncBatchModel._default_manager.filter(idempotency_key=idempotency_key)
            .values("batch_id", "run_id")
            .first()
        )
        current_by_id = (
            SyncBatchModel._default_manager.filter(batch_id=batch_id)
            .values("batch_id", "run_id")
            .first()
        )
        for current in (current_by_key, current_by_id):
            if current is None:
                continue
            current_run_id = current["run_id"]
            current_batch_id = current["batch_id"]
            if type(current_run_id) is not UUID or type(current_batch_id) is not UUID:
                raise ValueError("sync batch identity is invalid")
            if current_run_id not in run_rows:
                raise ValueError("sync batch parent changed while acquiring locks")
            batch_ids.add(current_batch_id)
        locked_batches = lock_batch_rows(batch_ids)
        for candidate_run_id in run_ids:
            run_row = run_rows.get(candidate_run_id)
            ensure_generic_run_write_allowed(
                candidate_run_id, run_row.trigger if run_row is not None else ""
            )
        ensure_generic_batch_write_allowed(
            batch_id=batch_id, run_id=run_id, idempotency_key=idempotency_key
        )
        for existing_row in locked_batches.values():
            if existing_row.run_id not in run_rows:
                raise ValueError("sync batch parent was not locked before its batch row")
            ensure_generic_batch_write_allowed(
                batch_id=existing_row.batch_id,
                run_id=existing_row.run_id,
                idempotency_key=existing_row.idempotency_key,
            )
        yield


@contextmanager
def guarded_generic_checkpoint_write(
    *,
    run_id: UUID,
    batch_id: UUID,
    checkpoint_id: UUID,
    cursor_name: str,
) -> Iterator[None]:
    """Lock a checkpoint's complete run/batch namespace before its upsert."""

    if cursor_name.startswith(CAPTURE_CHECKPOINT_PREFIX):
        reject_reserved_write()
    batch_probe = SyncBatchModel._default_manager.filter(batch_id=batch_id).values("run_id").first()
    checkpoint_probe = (
        SyncCheckpointModel._default_manager.filter(checkpoint_id=checkpoint_id)
        .values("run_id", "batch_id")
        .first()
    )
    run_ids = {run_id}
    batch_ids = {batch_id}
    if batch_probe is not None:
        parent_run_id = batch_probe["run_id"]
        if type(parent_run_id) is not UUID:
            raise ValueError("sync checkpoint parent identity is invalid")
        run_ids.add(parent_run_id)
    if checkpoint_probe is not None:
        existing_run_id = checkpoint_probe["run_id"]
        existing_batch_id = checkpoint_probe["batch_id"]
        if type(existing_run_id) is not UUID or type(existing_batch_id) is not UUID:
            raise ValueError("sync checkpoint identity is invalid")
        run_ids.add(existing_run_id)
        batch_ids.add(existing_batch_id)
    with transaction.atomic():
        run_rows = lock_run_rows(run_ids)
        current_batch = (
            SyncBatchModel._default_manager.filter(batch_id=batch_id).values("run_id").first()
        )
        current_checkpoint = (
            SyncCheckpointModel._default_manager.filter(checkpoint_id=checkpoint_id)
            .values("run_id", "batch_id")
            .first()
        )
        if current_batch is not None:
            parent_run_id = current_batch["run_id"]
            if type(parent_run_id) is not UUID or parent_run_id not in run_rows:
                raise ValueError("sync checkpoint parent changed while acquiring locks")
        if current_checkpoint is not None:
            existing_run_id = current_checkpoint["run_id"]
            existing_batch_id = current_checkpoint["batch_id"]
            if (
                type(existing_run_id) is not UUID
                or type(existing_batch_id) is not UUID
                or existing_run_id not in run_rows
            ):
                raise ValueError("sync checkpoint identity changed while acquiring locks")
            batch_ids.add(existing_batch_id)
        batch_rows = lock_batch_rows(batch_ids)
        for locked_batch in batch_rows.values():
            if locked_batch.run_id not in run_rows:
                raise ValueError("sync checkpoint parent was not locked before its batch row")
        for candidate_run_id in run_ids:
            run_row = run_rows.get(candidate_run_id)
            ensure_generic_run_write_allowed(
                candidate_run_id, run_row.trigger if run_row is not None else ""
            )
        ensure_generic_checkpoint_write_allowed(
            run_id=run_id, batch_id=batch_id, cursor_name=cursor_name
        )
        for locked_batch in batch_rows.values():
            ensure_generic_batch_write_allowed(
                batch_id=locked_batch.batch_id,
                run_id=locked_batch.run_id,
                idempotency_key=locked_batch.idempotency_key,
            )
        yield


__all__ = [
    "CAPTURE_CHECKPOINT_PREFIX",
    "CAPTURE_IDEMPOTENCY_PREFIX",
    "CAPTURE_TRIGGER",
    "capture_batch_is_reserved",
    "capture_run_is_reserved",
    "ensure_generic_batch_write_allowed",
    "ensure_generic_checkpoint_write_allowed",
    "ensure_generic_run_write_allowed",
    "guarded_generic_batch_write",
    "guarded_generic_checkpoint_write",
    "lock_batch_rows",
    "lock_run_rows",
    "reject_reserved_write",
]
