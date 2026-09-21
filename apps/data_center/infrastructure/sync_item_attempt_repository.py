"""Durable repository for DATA-02 per-item sync attempts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, connection, models, transaction
from django.db.models import Max, Q

from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
)

from .models import SyncBatchModel, SyncItemAttemptModel
from .sync_item_attempt_models import (
    _activate_sync_item_attempt_persistence,
    _activate_sync_item_attempt_transition,
)


def _uuid(value: str) -> UUID:
    """Convert a domain identifier to a Django UUID."""

    return UUID(value)


def _update_postgresql_item_attempt_terminals(
    terminal_models: Sequence[SyncItemAttemptModel],
) -> int:
    """Apply heterogeneous terminal values with one PostgreSQL VALUES update."""

    if not terminal_models:
        return 0
    row_placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s)"] * len(terminal_models))
    parameters: list[Any] = []
    for model in terminal_models:
        parameters.extend(
            (
                model.attempt_id,
                model.state,
                model.finished_at,
                model.stored_count,
                model.error_code,
                model.error_message,
                model.evidence_hash,
                model.updated_at,
            )
        )
    parameters.append(SyncItemAttemptState.RUNNING.value)
    table_name = connection.ops.quote_name(SyncItemAttemptModel._meta.db_table)
    statement = f"""
        UPDATE {table_name} AS target
        SET state = source.state::varchar,
            finished_at = source.finished_at::timestamptz,
            stored_count = source.stored_count::integer,
            error_code = source.error_code::varchar,
            error_message = source.error_message::text,
            evidence_hash = source.evidence_hash::varchar,
            updated_at = source.updated_at::timestamptz
        FROM (VALUES {row_placeholders}) AS source(
            attempt_id, state, finished_at, stored_count, error_code,
            error_message, evidence_hash, updated_at
        )
        WHERE target.attempt_id = source.attempt_id::uuid
          AND target.state = %s
    """
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        return cast(int, cursor.rowcount)


class SyncItemAttemptRepository:
    """Persist append-only retry history with one terminal transition per attempt."""

    def begin(self, attempt: SyncItemAttempt) -> SyncItemAttempt:
        """Insert one RUNNING attempt after locking and validating its batch."""

        return self.begin_many((attempt,))[0]

    def begin_many(self, attempts: Sequence[SyncItemAttempt]) -> list[SyncItemAttempt]:
        """Atomically insert one batch of validated RUNNING item attempts."""

        items = tuple(attempts)
        if not items:
            return []
        if any(not isinstance(attempt, SyncItemAttempt) for attempt in items):
            raise TypeError("attempts must contain only SyncItemAttempt values")
        if any(attempt.state is not SyncItemAttemptState.RUNNING for attempt in items):
            raise ValueError("begin_many requires RUNNING SyncItemAttempt values")
        batch_ids = {str(_uuid(attempt.batch_id)) for attempt in items}
        if len(batch_ids) != 1:
            raise ValueError("begin_many requires one stable batch")
        requested_scopes = {(attempt.asset_code, attempt.phase.value) for attempt in items}
        if len(requested_scopes) != len(items):
            raise ValueError("begin_many contains duplicate item phase scopes")
        batch_id = str(_uuid(items[0].batch_id))
        with transaction.atomic():
            batch = (
                SyncBatchModel._default_manager.select_for_update()
                .filter(batch_id=_uuid(batch_id))
                .first()
            )
            if batch is None:
                raise ValueError("sync item attempt requires an existing batch")
            if any(
                str(batch.run_id) != str(_uuid(attempt.run_id))
                or batch.dataset_key != attempt.dataset_key
                for attempt in items
            ):
                raise ValueError("sync item attempt batch identity mismatch")
            batch_attempts = SyncItemAttemptModel._default_manager.filter(batch_id=_uuid(batch_id))
            universe_hashes = {attempt.universe_hash for attempt in items}
            authority_hashes = {attempt.authority_content_hash for attempt in items}
            if (
                len(universe_hashes) != 1
                or batch_attempts.exclude(universe_hash=items[0].universe_hash).exists()
            ):
                raise ValueError("sync item attempt batch universe_hash mismatch")
            if (
                len(authority_hashes) != 1
                or batch_attempts.exclude(
                    authority_content_hash=items[0].authority_content_hash
                ).exists()
            ):
                raise ValueError("sync item attempt batch authority_content_hash mismatch")
            scope_rows = (
                SyncItemAttemptModel._default_manager.filter(
                    batch_id=_uuid(batch_id),
                    asset_code__in={attempt.asset_code for attempt in items},
                    phase__in={attempt.phase.value for attempt in items},
                )
                .values("asset_code", "phase")
                .annotate(
                    latest=Max("attempt_number"),
                    active=models.Count(
                        "attempt_id",
                        filter=Q(state=SyncItemAttemptState.RUNNING.value),
                    ),
                )
            )
            latest_by_scope: dict[tuple[str, str], int] = {}
            active_scopes: set[tuple[str, str]] = set()
            for row in scope_rows:
                scope_key = (str(row["asset_code"]), str(row["phase"]))
                if scope_key not in requested_scopes:
                    continue
                latest_by_scope[scope_key] = int(row["latest"] or 0)
                if int(row["active"] or 0) > 0:
                    active_scopes.add(scope_key)
            if active_scopes:
                raise ValueError("active attempt already exists for this item phase")
            for attempt in items:
                scope_key = (attempt.asset_code, attempt.phase.value)
                expected_number = latest_by_scope.get(scope_key, 0) + 1
                if attempt.attempt_number != expected_number:
                    raise ValueError(
                        f"attempt_number must be the next monotonic value {expected_number}"
                    )
            models_to_create = [
                SyncItemAttemptModel(
                    attempt_id=_uuid(attempt.attempt_id),
                    run_id=_uuid(attempt.run_id),
                    batch_id=_uuid(attempt.batch_id),
                    dataset_key=attempt.dataset_key,
                    asset_code=attempt.asset_code,
                    phase=attempt.phase.value,
                    attempt_number=attempt.attempt_number,
                    state=attempt.state.value,
                    execution_token=attempt.execution_token,
                    started_at=attempt.started_at,
                    finished_at=None,
                    stored_count=0,
                    error_code="",
                    error_message="",
                    universe_hash=attempt.universe_hash,
                    authority_content_hash=attempt.authority_content_hash,
                    evidence_hash="",
                )
                for attempt in items
            ]
            try:
                with _activate_sync_item_attempt_persistence():
                    persisted = SyncItemAttemptModel._default_manager.bulk_create(
                        models_to_create,
                        batch_size=200,
                    )
            except IntegrityError as exc:
                raise ValueError("sync item attempt identity conflict") from exc
        return [model.to_domain() for model in persisted]

    def finish(self, attempt: SyncItemAttempt) -> SyncItemAttempt:
        """Apply the sole RUNNING-to-terminal transition for an attempt."""

        return self.finish_many((attempt,))[0]

    def finish_many(self, attempts: Sequence[SyncItemAttempt]) -> list[SyncItemAttempt]:
        """Atomically apply terminal transitions to one stable batch."""

        items = tuple(attempts)
        if not items:
            return []
        if any(not isinstance(attempt, SyncItemAttempt) for attempt in items):
            raise TypeError("attempts must contain only SyncItemAttempt values")
        if any(
            attempt.state is SyncItemAttemptState.RUNNING or attempt.finished_at is None
            for attempt in items
        ):
            raise ValueError("finish_many requires terminal SyncItemAttempt values")
        batch_ids = {str(_uuid(attempt.batch_id)) for attempt in items}
        normalized_attempt_ids = [str(_uuid(attempt.attempt_id)) for attempt in items]
        attempt_ids = set(normalized_attempt_ids)
        if len(batch_ids) != 1:
            raise ValueError("finish_many requires one stable batch")
        if len(attempt_ids) != len(items):
            raise ValueError("finish_many contains duplicate attempt identities")
        with transaction.atomic():
            batch_exists = (
                SyncBatchModel._default_manager.select_for_update()
                .filter(batch_id=_uuid(next(iter(batch_ids))))
                .exists()
            )
            if not batch_exists:
                raise ValueError("sync item attempt requires an existing batch")
            locked_models = list(
                SyncItemAttemptModel._default_manager.select_for_update().filter(
                    attempt_id__in=[_uuid(attempt_id) for attempt_id in normalized_attempt_ids]
                )
            )
            if len(locked_models) != len(items):
                raise ValueError("sync item attempt does not exist")
            models_by_id = {str(model.attempt_id): model for model in locked_models}
            immutable_fields = (
                "run_id",
                "batch_id",
                "dataset_key",
                "asset_code",
                "phase",
                "attempt_number",
                "execution_token",
                "started_at",
                "universe_hash",
                "authority_content_hash",
            )
            for attempt in items:
                model = models_by_id[str(_uuid(attempt.attempt_id))]
                current = model.to_domain()
                if current.state is not SyncItemAttemptState.RUNNING:
                    raise ValueError("sync item attempt is already terminal")
                if attempt.finished_at is None:  # narrowed after the batch preflight
                    raise ValueError("finish_many requires terminal SyncItemAttempt values")
                for field_name in immutable_fields:
                    current_value = getattr(current, field_name)
                    attempt_value = getattr(attempt, field_name)
                    if field_name in {"run_id", "batch_id"}:
                        current_value = str(_uuid(str(current_value)))
                        attempt_value = str(_uuid(str(attempt_value)))
                    if current_value != attempt_value:
                        raise ValueError(f"sync item attempt identity conflict for {field_name}")
                model.state = attempt.state.value
                model.finished_at = attempt.finished_at
                model.stored_count = attempt.stored_count
                model.error_code = attempt.error_code
                model.error_message = attempt.error_message
                model.evidence_hash = attempt.evidence_hash
                model.updated_at = attempt.finished_at
            first = items[0]
            if first.finished_at is None:  # narrowed after the batch preflight
                raise ValueError("finish_many requires terminal SyncItemAttempt values")
            uniform_terminal = all(
                (
                    attempt.state,
                    attempt.finished_at,
                    attempt.stored_count,
                    attempt.error_code,
                    attempt.error_message,
                    attempt.evidence_hash,
                )
                == (
                    first.state,
                    first.finished_at,
                    first.stored_count,
                    first.error_code,
                    first.error_message,
                    first.evidence_hash,
                )
                for attempt in items
            )
            with _activate_sync_item_attempt_transition():
                if uniform_terminal:
                    updated = SyncItemAttemptModel._default_manager.filter(
                        attempt_id__in=[model.attempt_id for model in locked_models],
                        state=SyncItemAttemptState.RUNNING.value,
                    ).update(
                        state=first.state.value,
                        finished_at=first.finished_at,
                        stored_count=first.stored_count,
                        error_code=first.error_code,
                        error_message=first.error_message,
                        evidence_hash=first.evidence_hash,
                        updated_at=first.finished_at,
                    )
                elif connection.vendor == "postgresql":
                    updated = _update_postgresql_item_attempt_terminals(locked_models)
                else:
                    updated = SyncItemAttemptModel._default_manager.bulk_update(
                        locked_models,
                        fields=[
                            "state",
                            "finished_at",
                            "stored_count",
                            "error_code",
                            "error_message",
                            "evidence_hash",
                            "updated_at",
                        ],
                        batch_size=200,
                    )
            if updated != len(items):
                raise ValueError("sync item attempt terminal transition conflict")
        return [models_by_id[str(_uuid(attempt.attempt_id))].to_domain() for attempt in items]

    def next_attempt_number(
        self,
        *,
        batch_id: str,
        asset_code: str,
        phase: SyncItemAttemptPhase,
    ) -> int:
        """Return the next number after all retained attempts in one item phase."""

        return self.next_attempt_numbers(
            batch_id=batch_id,
            asset_codes=(asset_code,),
            phase=phase,
        )[asset_code]

    def next_attempt_numbers(
        self,
        *,
        batch_id: str,
        asset_codes: Sequence[str],
        phase: SyncItemAttemptPhase,
    ) -> dict[str, int]:
        """Return next monotonic numbers for a unique set of item scopes."""

        codes = tuple(asset_codes)
        if len(set(codes)) != len(codes):
            raise ValueError("asset_codes must be unique")
        latest_rows = (
            SyncItemAttemptModel._default_manager.filter(
                batch_id=_uuid(batch_id),
                asset_code__in=codes,
                phase=phase.value,
            )
            .values("asset_code")
            .annotate(latest=Max("attempt_number"))
        )
        latest_by_code = {str(row["asset_code"]): int(row["latest"] or 0) for row in latest_rows}
        return {asset_code: latest_by_code.get(asset_code, 0) + 1 for asset_code in codes}

    def recover_interrupted(
        self,
        *,
        batch_id: str,
        phase: SyncItemAttemptPhase,
        before: datetime,
        finished_at: datetime,
    ) -> list[SyncItemAttempt]:
        """Explicitly close stale RUNNING rows before a later retry begins."""

        if before.tzinfo is None or before.utcoffset() is None:
            raise ValueError("before must be timezone-aware")
        with transaction.atomic():
            batch = (
                SyncBatchModel._default_manager.select_for_update()
                .filter(batch_id=_uuid(batch_id))
                .first()
            )
            if batch is None:
                raise ValueError("sync item attempt recovery requires an existing batch")
            models_to_finish = list(
                SyncItemAttemptModel._default_manager.select_for_update()
                .filter(
                    batch_id=_uuid(batch_id),
                    phase=phase.value,
                    state=SyncItemAttemptState.RUNNING.value,
                    started_at__lt=before,
                )
                .order_by("asset_code", "attempt_number")
            )
            interrupted = [
                model.to_domain().finish(
                    state=SyncItemAttemptState.INTERRUPTED,
                    finished_at=finished_at,
                    error_code="interrupted_before_retry",
                )
                for model in models_to_finish
            ]
            for model, attempt in zip(models_to_finish, interrupted, strict=True):
                if attempt.finished_at is None:  # domain finish always supplies this value
                    raise ValueError("recovered item attempt requires finished_at")
                model.state = attempt.state.value
                model.finished_at = attempt.finished_at
                model.error_code = attempt.error_code
                model.error_message = attempt.error_message
                model.updated_at = attempt.finished_at
            with _activate_sync_item_attempt_transition():
                updated = SyncItemAttemptModel._default_manager.filter(
                    attempt_id__in=[model.attempt_id for model in models_to_finish],
                    state=SyncItemAttemptState.RUNNING.value,
                ).update(
                    state=SyncItemAttemptState.INTERRUPTED.value,
                    finished_at=finished_at,
                    error_code="interrupted_before_retry",
                    error_message="",
                    updated_at=finished_at,
                )
            if updated != len(interrupted):
                raise ValueError("sync item attempt recovery transition conflict")
        return interrupted

    def list_for_batch(self, batch_id: str) -> list[SyncItemAttempt]:
        """Return complete attempt history for a batch in deterministic order."""

        return [
            model.to_domain()
            for model in SyncItemAttemptModel._default_manager.filter(
                batch_id=_uuid(batch_id)
            ).order_by("asset_code", "phase", "attempt_number")
        ]


__all__ = ["SyncItemAttemptRepository"]
