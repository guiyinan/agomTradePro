"""Durable item-attempt contracts for resumable DATA-02 backfills."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.data_center.application.backfill_control_plane import (
    backfill_control_plane_ids,
    backfill_execution_token,
)
from apps.data_center.composition import (
    get_backfill_item_attempt_store,
    get_sync_item_attempt_repository,
)
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
from apps.data_center.infrastructure.sync_item_attempt_models import (
    _activate_sync_item_attempt_persistence,
    _activate_sync_item_attempt_transition,
)

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
    publication = replace(
        SyncItemAttempt(**common, state=SyncItemAttemptState.RUNNING),
        phase=SyncItemAttemptPhase.PUBLICATION,
    )
    with pytest.raises(ValueError, match="publication attempt requires evidence_hash"):
        publication.finish(
            state=SyncItemAttemptState.SUCCEEDED,
            finished_at=NOW + timedelta(seconds=1),
            stored_count=1,
        )


def test_sync_item_attempt_repository_is_available_from_composition() -> None:
    """Runtime wiring exposes the guarded repository through the composition root."""

    assert isinstance(get_sync_item_attempt_repository(), SyncItemAttemptRepository)


@pytest.mark.django_db
def test_backfill_item_attempt_store_creates_stable_batch_before_attempt() -> None:
    """Runtime wiring creates the deterministic batch before item evidence."""

    store = get_backfill_item_attempt_store()
    idempotency_key = "equity.core.backfill:tushare:offset=0:window=2:abc123"
    execution_token = backfill_execution_token(idempotency_key)

    attempt = store.begin(
        idempotency_key=idempotency_key,
        provider_name="tushare",
        asset_code="000001.SZ",
        phase=SyncItemAttemptPhase.QUOTE,
        execution_token=execution_token,
        started_at=NOW,
        universe_hash=UNIVERSE_HASH,
        authority_content_hash=AUTHORITY_HASH,
        requested=2,
    )

    expected_run_id, expected_batch_id = backfill_control_plane_ids(idempotency_key)
    assert attempt.run_id == expected_run_id
    assert attempt.batch_id == expected_batch_id
    assert attempt.execution_token == execution_token
    assert attempt.attempt_number == 1
    assert attempt.state is SyncItemAttemptState.RUNNING

    finished = store.finish(
        attempt,
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=NOW + timedelta(seconds=1),
        stored_count=1,
    )
    assert finished.state is SyncItemAttemptState.SUCCEEDED
    assert finished.stored_count == 1


@pytest.mark.django_db
def test_backfill_item_attempt_store_recovers_only_stale_attempts() -> None:
    """A recent execution blocks overlap while an expired execution is retained."""

    store = get_backfill_item_attempt_store()
    idempotency_key = "equity.core.backfill:tushare:offset=0:window=1:def456"
    common = {
        "idempotency_key": idempotency_key,
        "provider_name": "tushare",
        "asset_code": "000001.SZ",
        "phase": SyncItemAttemptPhase.PRICE,
        "execution_token": backfill_execution_token(idempotency_key),
        "universe_hash": UNIVERSE_HASH,
        "authority_content_hash": AUTHORITY_HASH,
        "requested": 1,
    }
    first = store.begin(started_at=NOW, **common)

    with pytest.raises(ValueError, match="active attempt already exists"):
        get_backfill_item_attempt_store().begin(
            started_at=NOW + timedelta(minutes=30),
            **common,
        )

    second = get_backfill_item_attempt_store().begin(
        started_at=NOW + timedelta(seconds=3902),
        **common,
    )

    assert second.attempt_number == 2
    attempts = SyncItemAttemptRepository().list_for_batch(first.batch_id)
    assert [(item.attempt_number, item.state) for item in attempts] == [
        (1, SyncItemAttemptState.INTERRUPTED),
        (2, SyncItemAttemptState.RUNNING),
    ]


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
def test_sync_item_attempt_repository_bulk_transition_is_complete_and_atomic() -> None:
    """A bounded phase batch inserts and reaches terminal state as one unit."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running_attempts = [
        _running_attempt(batch, asset_code=f"{index:06d}.SZ") for index in range(1, 201)
    ]

    persisted = repository.begin_many(running_attempts)
    assert persisted == running_attempts
    terminal = [
        attempt.finish(
            state=SyncItemAttemptState.SUCCEEDED,
            finished_at=NOW + timedelta(seconds=1),
            stored_count=1,
        )
        for attempt in persisted
    ]
    assert repository.finish_many(terminal) == terminal

    rows = repository.list_for_batch(batch.batch_id)
    assert len(rows) == 200
    assert all(item.state is SyncItemAttemptState.SUCCEEDED for item in rows)
    assert all(item.attempt_number == 1 for item in rows)


@pytest.mark.django_db
def test_sync_item_attempt_repository_bulk_transition_preserves_mixed_outcomes() -> None:
    """Mixed item outcomes retain their own counts and error evidence."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running = repository.begin_many(
        [
            _running_attempt(batch, asset_code="000001.SZ"),
            _running_attempt(batch, asset_code="000002.SZ"),
        ]
    )
    terminal = [
        running[0].finish(
            state=SyncItemAttemptState.SUCCEEDED,
            finished_at=NOW + timedelta(seconds=1),
            stored_count=3,
        ),
        running[1].finish(
            state=SyncItemAttemptState.FAILED,
            finished_at=NOW + timedelta(seconds=1),
            error_code="zero_output",
        ),
    ]

    assert repository.finish_many(terminal) == terminal
    rows = repository.list_for_batch(batch.batch_id)
    assert [(item.state, item.stored_count, item.error_code) for item in rows] == [
        (SyncItemAttemptState.SUCCEEDED, 3, ""),
        (SyncItemAttemptState.FAILED, 0, "zero_output"),
    ]


@pytest.mark.django_db
def test_sync_item_attempt_repository_canonicalizes_uuid_spellings() -> None:
    """Equivalent UUID spellings resolve to the same persisted attempt identity."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    running = _running_attempt(batch)
    alternate_running = replace(
        running,
        run_id="{" + running.run_id.upper() + "}",
        batch_id="{" + running.batch_id.upper() + "}",
    )

    persisted = repository.begin(alternate_running)
    terminal = persisted.finish(
        state=SyncItemAttemptState.SUCCEEDED,
        finished_at=NOW + timedelta(seconds=1),
        stored_count=1,
    )
    alternate_terminal = replace(
        terminal,
        attempt_id="{" + terminal.attempt_id.upper() + "}",
        run_id=terminal.run_id.upper(),
        batch_id=terminal.batch_id.upper(),
    )

    finished = repository.finish(alternate_terminal)

    assert finished.attempt_id == running.attempt_id
    assert finished.run_id == batch.run_id
    assert finished.batch_id == batch.batch_id
    assert finished.state is SyncItemAttemptState.SUCCEEDED


@pytest.mark.django_db
def test_sync_item_attempt_repository_bulk_rejection_leaves_no_partial_rows() -> None:
    """One invalid expected number rolls back every insert in the phase batch."""

    batch = _saved_batch()
    repository = SyncItemAttemptRepository()
    attempts = [
        _running_attempt(batch, asset_code="000001.SZ"),
        _running_attempt(batch, asset_code="000002.SZ", attempt_number=2),
    ]

    with pytest.raises(ValueError, match="next monotonic value 1"):
        repository.begin_many(attempts)

    assert repository.list_for_batch(batch.batch_id) == []


@pytest.mark.django_db
def test_sync_item_attempt_manager_keeps_bulk_mutations_repository_owned() -> None:
    """Callers cannot use public ORM bulk methods to bypass lifecycle checks."""

    batch = _saved_batch()
    attempt = _running_attempt(batch)
    model = SyncItemAttemptModel(
        attempt_id=attempt.attempt_id,
        run_id=attempt.run_id,
        batch_id=attempt.batch_id,
        dataset_key=attempt.dataset_key,
        asset_code=attempt.asset_code,
        phase=attempt.phase.value,
        attempt_number=attempt.attempt_number,
        state=attempt.state.value,
        execution_token=attempt.execution_token,
        started_at=attempt.started_at,
        universe_hash=attempt.universe_hash,
        authority_content_hash=attempt.authority_content_hash,
    )

    with pytest.raises(ValidationError, match="repository persistence"):
        SyncItemAttemptModel._default_manager.bulk_create([model])
    with pytest.raises(ValidationError, match="repository transition"):
        SyncItemAttemptModel._default_manager.bulk_update([model], ["state"])


@pytest.mark.django_db
def test_sync_item_attempt_private_bulk_scopes_reject_upserts_and_identity_updates() -> None:
    """Repository capabilities cannot upsert rows or rewrite immutable identity fields."""

    batch = _saved_batch()
    attempt = _running_attempt(batch)
    model = SyncItemAttemptModel(
        attempt_id=attempt.attempt_id,
        run_id=attempt.run_id,
        batch_id=attempt.batch_id,
        dataset_key=attempt.dataset_key,
        asset_code=attempt.asset_code,
        phase=attempt.phase.value,
        attempt_number=attempt.attempt_number,
        state=attempt.state.value,
        execution_token=attempt.execution_token,
        started_at=attempt.started_at,
        universe_hash=attempt.universe_hash,
        authority_content_hash=attempt.authority_content_hash,
    )

    with _activate_sync_item_attempt_persistence():
        with pytest.raises(ValidationError, match="bulk conflicts"):
            SyncItemAttemptModel._default_manager.bulk_create([model], ignore_conflicts=True)

    persisted = SyncItemAttemptRepository().begin(attempt)
    persisted_model = SyncItemAttemptModel._default_manager.get(attempt_id=persisted.attempt_id)
    with _activate_sync_item_attempt_transition():
        with pytest.raises(ValidationError, match="fields are restricted"):
            SyncItemAttemptModel._default_manager.filter(attempt_id=persisted.attempt_id).update(
                asset_code="000002.SZ"
            )
        with pytest.raises(ValidationError, match="fields are restricted"):
            SyncItemAttemptModel._default_manager.bulk_update([persisted_model], ["asset_code"])


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
def test_sync_item_attempt_database_rejects_two_running_rows_for_one_phase() -> None:
    """A partial unique constraint protects the gate outside repository code."""

    batch = _saved_batch()
    first = _running_attempt(batch)
    SyncItemAttemptRepository().begin(first)
    duplicate = _running_attempt(batch, attempt_number=2)

    with pytest.raises(IntegrityError), transaction.atomic():
        SyncItemAttemptModel._default_manager.create(
            attempt_id=duplicate.attempt_id,
            run_id=duplicate.run_id,
            batch_id=duplicate.batch_id,
            dataset_key=duplicate.dataset_key,
            asset_code=duplicate.asset_code,
            phase=duplicate.phase.value,
            attempt_number=duplicate.attempt_number,
            state=duplicate.state.value,
            execution_token=duplicate.execution_token,
            started_at=duplicate.started_at,
            universe_hash=duplicate.universe_hash,
            authority_content_hash=duplicate.authority_content_hash,
        )


@pytest.mark.django_db
def test_sync_item_attempt_recovery_requires_existing_locked_batch() -> None:
    """Recovery cannot operate outside the canonical batch lock order."""

    with pytest.raises(ValueError, match="recovery requires an existing batch"):
        SyncItemAttemptRepository().recover_interrupted(
            batch_id=str(uuid4()),
            phase=SyncItemAttemptPhase.QUOTE,
            before=NOW,
            finished_at=NOW,
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
