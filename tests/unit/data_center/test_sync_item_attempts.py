"""Durable item-attempt contracts for resumable DATA-02 backfills."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.data_center.composition import get_sync_item_attempt_repository
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
    SyncItemState,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncBatchRepository,
    SyncItemAttemptRepository,
)
from apps.data_center.infrastructure.models import SyncItemAttemptModel

NOW = datetime(2026, 9, 21, 6, 30, tzinfo=UTC)
UNIVERSE_HASH = "b" * 64
AUTHORITY_HASH = "a" * 64


def _saved_batch() -> SyncBatch:
    run_id = str(uuid4())
    batch = SyncBatch(
        batch_id=str(uuid4()),
        run_id=run_id,
        dataset_key="equity.core.backfill",
        provider_name="tushare",
        idempotency_key=f"equity.core.backfill:tushare:{uuid4()}",
        state=SyncItemState.RUNNING,
        requested=2,
        started_at=NOW,
    )
    return SyncBatchRepository().save(batch)


def _running_attempt(
    batch: SyncBatch,
    *,
    asset_code: str = "000001.SZ",
    attempt_number: int = 1,
) -> SyncItemAttempt:
    return SyncItemAttempt(
        attempt_id=str(uuid4()),
        run_id=batch.run_id,
        batch_id=batch.batch_id,
        dataset_key=batch.dataset_key,
        asset_code=asset_code,
        phase=SyncItemAttemptPhase.QUOTE,
        attempt_number=attempt_number,
        state=SyncItemAttemptState.RUNNING,
        execution_token=f"task-{attempt_number}",
        started_at=NOW,
        universe_hash=UNIVERSE_HASH,
        authority_content_hash=AUTHORITY_HASH,
    )


def test_sync_item_attempt_domain_rejects_invalid_lifecycle() -> None:
    """Running and terminal records require distinct timestamp/error shapes."""

    batch_id = str(uuid4())
    run_id = str(uuid4())
    common = {
        "attempt_id": str(uuid4()),
        "run_id": run_id,
        "batch_id": batch_id,
        "dataset_key": "equity.core.backfill",
        "asset_code": "000001.SZ",
        "phase": SyncItemAttemptPhase.QUOTE,
        "attempt_number": 1,
        "execution_token": "task-1",
        "started_at": NOW,
        "universe_hash": UNIVERSE_HASH,
        "authority_content_hash": AUTHORITY_HASH,
    }
    with pytest.raises(ValueError, match="RUNNING.*finished_at"):
        SyncItemAttempt(
            **common,
            state=SyncItemAttemptState.RUNNING,
            finished_at=NOW,
        )
    with pytest.raises(ValueError, match="terminal.*finished_at"):
        SyncItemAttempt(
            **common,
            state=SyncItemAttemptState.FAILED,
            error_code="provider_failed",
        )
    with pytest.raises(ValueError, match="error_code"):
        SyncItemAttempt(
            **common,
            state=SyncItemAttemptState.INTERRUPTED,
            finished_at=NOW,
        )


def test_sync_item_attempt_repository_is_available_from_composition() -> None:
    """Runtime wiring exposes the guarded repository through the composition root."""

    assert isinstance(get_sync_item_attempt_repository(), SyncItemAttemptRepository)


@pytest.mark.django_db
def test_sync_item_attempt_repository_allows_one_terminal_transition() -> None:
    """An attempt may leave RUNNING once and its terminal evidence is immutable."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running = _running_attempt(batch)

    assert repository.begin(running) == running
    succeeded = running.finish(
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=NOW + timedelta(seconds=1),
        stored_count=1,
    )
    assert repository.finish(succeeded) == succeeded

    with pytest.raises(ValueError, match="already terminal"):
        repository.finish(
            running.finish(
                state=SyncItemAttemptState.FAILED,
                finished_at=NOW + timedelta(seconds=2),
                error_code="late_failure",
            )
        )
    model = SyncItemAttemptModel._default_manager.get(attempt_id=running.attempt_id)
    model.error_message = "tampered"
    with pytest.raises(ValidationError, match="repository transition"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()


@pytest.mark.django_db
def test_sync_item_attempt_retries_append_monotonic_history() -> None:
    """A retry receives a new number while interrupted evidence remains queryable."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    first = _running_attempt(batch)
    repository.begin(first)
    recovered = repository.recover_interrupted(
        batch_id=batch.batch_id,
        phase=SyncItemAttemptPhase.QUOTE,
        before=NOW + timedelta(seconds=1),
        finished_at=NOW + timedelta(seconds=1),
    )

    assert [item.state for item in recovered] == [SyncItemAttemptState.INTERRUPTED]

    assert (
        repository.next_attempt_number(
            batch_id=batch.batch_id,
            asset_code=first.asset_code,
            phase=first.phase,
        )
        == 2
    )
    second = _running_attempt(batch, attempt_number=2)
    repository.begin(second)

    attempts = repository.list_for_batch(batch.batch_id)
    assert [(item.attempt_number, item.state) for item in attempts] == [
        (1, SyncItemAttemptState.INTERRUPTED),
        (2, SyncItemAttemptState.RUNNING),
    ]


@pytest.mark.django_db
def test_sync_item_attempt_repository_rejects_active_duplicate() -> None:
    """Concurrent execution tokens cannot open a second attempt for one phase."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    first = _running_attempt(batch)
    repository.begin(first)

    duplicate = _running_attempt(batch, attempt_number=2)
    with pytest.raises(ValueError, match="active attempt already exists"):
        repository.begin(duplicate)


@pytest.mark.django_db
def test_sync_item_attempt_model_rejects_direct_terminal_insert() -> None:
    """Direct ORM creation cannot bypass the repository-owned transition."""

    batch = _saved_batch()
    attempt = _running_attempt(batch)
    with pytest.raises(ValidationError, match="must start in RUNNING"):
        SyncItemAttemptModel._default_manager.create(
            attempt_id=attempt.attempt_id,
            run_id=attempt.run_id,
            batch_id=attempt.batch_id,
            dataset_key=attempt.dataset_key,
            asset_code=attempt.asset_code,
            phase=attempt.phase.value,
            attempt_number=attempt.attempt_number,
            state=SyncItemAttemptState.FAILED.value,
            execution_token=attempt.execution_token,
            started_at=attempt.started_at,
            finished_at=NOW + timedelta(seconds=1),
            stored_count=0,
            error_code="direct_insert",
            error_message="",
            universe_hash=attempt.universe_hash,
            authority_content_hash=attempt.authority_content_hash,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field_name", "mismatch", "error_match"),
    [
        ("universe_hash", "c" * 64, "batch universe_hash mismatch"),
        ("authority_content_hash", "d" * 64, "batch authority_content_hash mismatch"),
    ],
)
def test_sync_item_attempt_repository_binds_batch_hashes(
    field_name: str,
    mismatch: str,
    error_match: str,
) -> None:
    """Every phase and retry in one batch reuses its frozen evidence binding."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    first = _running_attempt(batch)
    repository.begin(first)
    repository.finish(
        first.finish(
            state=SyncItemAttemptState.SUCCEEDED,
            finished_at=NOW + timedelta(seconds=1),
            stored_count=1,
        )
    )
    mismatched = replace(
        _running_attempt(batch, asset_code="000002.SZ"),
        **{field_name: mismatch},
    )

    with pytest.raises(ValueError, match=error_match):
        repository.begin(mismatched)


@pytest.mark.django_db
def test_sync_item_attempt_repository_keeps_failures_beyond_response_preview() -> None:
    """Durable failure evidence is complete when the task response would stop at 20."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running_attempts = [_running_attempt(batch, asset_code=f"{index:06}.SZ") for index in range(25)]
    for attempt in running_attempts:
        repository.begin(attempt)
        repository.finish(
            attempt.finish(
                state=SyncItemAttemptState.FAILED,
                finished_at=NOW + timedelta(seconds=1),
                error_code="provider_failed",
            )
        )

    failures = repository.list_for_batch(batch.batch_id)
    assert len(failures) == 25
    assert {item.asset_code for item in failures} == {f"{index:06}.SZ" for index in range(25)}
    assert all(item.state is SyncItemAttemptState.FAILED for item in failures)
