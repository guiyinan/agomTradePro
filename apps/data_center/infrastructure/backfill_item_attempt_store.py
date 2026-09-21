"""Django-backed item-attempt store for DATA-02 backfill execution."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction

from apps.data_center.application.backfill_control_plane import backfill_control_plane_ids
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)

from .control_plane_repositories import (
    SyncBatchRepository,
    SyncItemAttemptRepository,
    SyncRunRepository,
)

_STALE_ATTEMPT_AGE = timedelta(seconds=3900)


class DjangoBackfillItemAttemptStore:
    """Persist item attempts against a stable, retry-safe backfill batch."""

    def __init__(
        self,
        *,
        run_repository: SyncRunRepository,
        batch_repository: SyncBatchRepository,
        attempt_repository: SyncItemAttemptRepository,
    ) -> None:
        self._run_repository = run_repository
        self._batch_repository = batch_repository
        self._attempt_repository = attempt_repository
        self._prepared_batches: set[str] = set()
        self._recovered_phases: set[tuple[str, SyncItemAttemptPhase]] = set()

    def begin(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        asset_code: str,
        phase: SyncItemAttemptPhase,
        execution_token: str,
        started_at: datetime,
        universe_hash: str,
        authority_content_hash: str,
        requested: int,
    ) -> SyncItemAttempt:
        """Start the next item attempt after ensuring its stable batch exists."""

        run_id, batch_id = backfill_control_plane_ids(idempotency_key)
        if idempotency_key not in self._prepared_batches:
            with transaction.atomic():
                self._run_repository.save(
                    SyncRun(
                        run_id=run_id,
                        dataset_key="equity.core.backfill",
                        trigger="celery.backfill_a_share_core",
                        status=SyncRunStatus.FETCHING,
                        outcome="blocked",
                        requested=requested,
                        provider_name=provider_name or "unknown",
                        contract_version="1.0",
                        started_at=started_at,
                    )
                )
                self._batch_repository.save(
                    SyncBatch(
                        batch_id=batch_id,
                        run_id=run_id,
                        dataset_key="equity.core.backfill",
                        provider_name=provider_name or "unknown",
                        idempotency_key=idempotency_key,
                        state=SyncItemState.RUNNING,
                        requested=requested,
                        started_at=started_at,
                    )
                )
            self._prepared_batches.add(idempotency_key)
        recovery_key = (idempotency_key, phase)
        if recovery_key not in self._recovered_phases:
            self._attempt_repository.recover_interrupted(
                batch_id=batch_id,
                phase=phase,
                before=started_at - _STALE_ATTEMPT_AGE,
                finished_at=started_at,
            )
            self._recovered_phases.add(recovery_key)
        attempt_number = self._attempt_repository.next_attempt_number(
            batch_id=batch_id,
            asset_code=asset_code,
            phase=phase,
        )
        attempt_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    "agomtradepro:sync-item-attempt:"
                    f"{batch_id}:{asset_code}:{phase.value}:{attempt_number}"
                ),
            )
        )
        return self._attempt_repository.begin(
            SyncItemAttempt(
                attempt_id=attempt_id,
                run_id=run_id,
                batch_id=batch_id,
                dataset_key="equity.core.backfill",
                asset_code=asset_code,
                phase=phase,
                attempt_number=attempt_number,
                state=SyncItemAttemptState.RUNNING,
                execution_token=execution_token,
                started_at=started_at,
                universe_hash=universe_hash,
                authority_content_hash=authority_content_hash,
            )
        )

    def finish(
        self,
        attempt: SyncItemAttempt,
        *,
        state: SyncItemAttemptState,
        finished_at: datetime,
        stored_count: int = 0,
        error_code: str = "",
        error_message: str = "",
        evidence_hash: str = "",
    ) -> SyncItemAttempt:
        """Persist the sole terminal transition for one running attempt."""

        return self._attempt_repository.finish(
            attempt.finish(
                state=state,
                finished_at=finished_at,
                stored_count=stored_count,
                error_code=error_code,
                error_message=error_message,
                evidence_hash=evidence_hash,
            )
        )


__all__ = ["DjangoBackfillItemAttemptStore"]
