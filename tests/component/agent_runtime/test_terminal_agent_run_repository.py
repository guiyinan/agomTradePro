"""Database-backed contract tests for the dormant Terminal Agent run ledger.

The default SQLite run covers repository behavior quickly.  The PostgreSQL
cases are opt-in through ``tests.settings_terminal_agent_run_postgres`` and a
disposable database URL; they are the only evidence for cross-connection row
locking and rollback visibility.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import override_settings

from apps.account.infrastructure.models import AccountProfileModel
from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.domain.entities import TaskDomain, TaskStatus
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalOwnershipError,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)
from apps.agent_runtime.infrastructure.models import (
    AgentTaskModel,
    TerminalAgentRunModel,
)
from apps.agent_runtime.infrastructure.terminal_agent_run_repository import (
    TerminalAgentRunRepository,
    TerminalRunIdempotencyConflict,
    TerminalRunRepositoryError,
)

pytestmark = pytest.mark.django_db(transaction=True)

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def owner(db):
    """Create one authenticated owner for a disposable run record."""

    user_model = get_user_model()
    return user_model.objects.create_user(username=f"tar-owner-{uuid4().hex[:8]}")


@pytest.fixture
def task(owner):
    """Create a canonical AgentTask owned by the test actor."""

    return AgentTaskModel.objects.create(
        request_id=f"tar-task-{uuid4().hex[:20]}",
        task_domain=TaskDomain.RESEARCH.value,
        task_type="terminal_contract_test",
        status=TaskStatus.DRAFT.value,
        input_payload={"task_ref": "existing-agent-task-payload"},
        created_by=owner,
    )


@pytest.fixture
def repository() -> TerminalAgentRunRepository:
    """Build the infrastructure adapter under test."""

    return TerminalAgentRunRepository()


def _configure_terminal_payload(task, **fields: object) -> None:
    """Attach one worker-input payload to the canonical task fixture."""

    payload: dict[str, object] = {
        "message": "health check",
        "session_id": "session-repository-contract",
    }
    payload.update(fields)
    task.input_payload = {"terminal_agent": payload}
    task.save(update_fields=["input_payload", "updated_at"])


def _configure_owner_profile(owner, *, mcp_enabled: bool = True):
    """Create the authoritative account projection used by worker input tests."""

    profile, _ = AccountProfileModel.objects.get_or_create(
        user=owner,
        defaults={
            "display_name": owner.username,
            "rbac_role": "owner",
            "mcp_enabled": mcp_enabled,
            "approval_status": "approved",
        },
    )
    if profile.mcp_enabled != mcp_enabled:
        profile.mcp_enabled = mcp_enabled
        profile.save(update_fields=["mcp_enabled", "updated_at"])
    return profile


def _request(
    *,
    owner_id: int,
    task_id: int,
    suffix: str = "0001",
    digest: str = "a" * 64,
    message: str = "do not persist this prompt",
) -> TerminalQueuedSubmissionRequest:
    """Build a valid web-queued request with deterministic identity."""

    accepted_at = _NOW
    submission = TerminalRunSubmission(
        selector=TerminalRunSelector(
            run_id=f"run-{suffix}",
            task_id=task_id,
            actor_user_id=owner_id,
            client_request_id=f"request-{suffix}",
        ),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest=digest,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )
    return TerminalQueuedSubmissionRequest(submission=submission, message=message)


def test_submit_stores_owner_identity_and_no_raw_message(repository, owner, task):
    """Admission persists only dispatch metadata and returns a queued run."""

    result = repository.submit(_request(owner_id=owner.id, task_id=task.id))

    assert result.dispatch_status is TerminalRunStatus.QUEUED
    row = TerminalAgentRunModel.objects.get(run_id=result.submission.selector.run_id)
    assert row.actor_user_id == owner.id
    assert row.task_id == task.id
    assert row.request_digest == "a" * 64
    field_names = {field.name for field in TerminalAgentRunModel._meta.get_fields()}
    assert not {"message", "prompt", "input_payload"}.intersection(field_names)


def test_same_actor_client_key_and_digest_is_idempotent(repository, owner, task):
    """A replay returns one exact durable run without creating a second row."""

    request = _request(owner_id=owner.id, task_id=task.id)
    first = repository.submit(request)
    replay = repository.submit(replace(request, message="same identity, new transport text"))

    assert replay == first
    assert TerminalAgentRunModel.objects.count() == 1


def test_same_actor_client_key_with_different_digest_fails_closed(repository, owner, task):
    """A client key cannot be reused for a different request fingerprint."""

    repository.submit(_request(owner_id=owner.id, task_id=task.id))
    conflicting = _request(owner_id=owner.id, task_id=task.id, digest="b" * 64)

    with pytest.raises(TerminalRunIdempotencyConflict) as error:
        repository.submit(conflicting)

    assert error.value.reason_code == "IDEMPOTENCY_KEY_CONFLICT"
    assert TerminalAgentRunModel.objects.count() == 1


def test_admission_capacity_is_atomic_and_idempotent_replay_bypasses_limit(repository, owner, task):
    """One queued slot is enforced while an exact replay remains available."""

    first_request = _request(owner_id=owner.id, task_id=task.id, suffix="capacity-first")
    second_request = _request(owner_id=owner.id, task_id=task.id, suffix="capacity-second")

    with override_settings(
        TERMINAL_PER_USER_ACTIVE_LIMIT=1,
        TERMINAL_PER_USER_QUEUED_LIMIT=1,
        TERMINAL_GLOBAL_ACTIVE_LIMIT=10,
        TERMINAL_GLOBAL_QUEUED_LIMIT=10,
    ):
        first = repository.submit(first_request)
        with pytest.raises(TerminalRunRepositoryError) as rejected:
            repository.submit(second_request)
        replay = repository.submit(replace(first_request, message="replayed"))

    assert rejected.value.reason_code == "per_user_queued_limit"
    assert replay == first
    assert TerminalAgentRunModel.objects.count() == 1


def test_owner_scope_hides_other_actor_and_rejects_foreign_task(repository, owner, task):
    """Status reads and admission cannot cross the canonical AgentTask owner."""

    result = repository.submit(_request(owner_id=owner.id, task_id=task.id))
    other_user = get_user_model().objects.create_user(username=f"tar-other-{uuid4().hex[:8]}")

    assert (
        repository.get_for_owner(
            run_id=result.submission.selector.run_id,
            actor_user_id=other_user.id,
        )
        is None
    )

    foreign_request = _request(owner_id=other_user.id, task_id=task.id, suffix="0002")
    with pytest.raises(TerminalOwnershipError, match="RUN_NOT_OWNER"):
        repository.submit(foreign_request)


def test_outer_transaction_rollback_removes_admitted_run(repository, owner, task):
    """The repository's nested atomic block remains rollback-safe for callers."""

    request = _request(owner_id=owner.id, task_id=task.id)
    with pytest.raises(RuntimeError, match="rollback sentinel"):
        with transaction.atomic():
            repository.submit(request)
            raise RuntimeError("rollback sentinel")

    assert not TerminalAgentRunModel.objects.filter(
        run_id=request.submission.selector.run_id
    ).exists()


def test_claim_is_first_winner_and_replay_is_noop(repository, owner, task):
    """One worker transitions queued to claimed; a later worker cannot reclaim it."""

    request = _request(owner_id=owner.id, task_id=task.id)
    repository.submit(request)

    first = repository.claim(
        run_id=request.submission.selector.run_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    second = repository.claim(
        run_id=request.submission.selector.run_id,
        worker_id="worker-b",
        claimed_at=_NOW + timedelta(seconds=1),
    )

    assert first is not None
    assert first.dispatch_status is TerminalRunStatus.CLAIMED
    assert first.claimed_by == "worker-a"
    assert first.heartbeat_at == _NOW
    assert second is None


def test_transition_is_owner_scoped_and_requires_worker_for_claim(repository, owner, task):
    """Lifecycle transitions use the domain graph and never cross owners."""

    request = _request(owner_id=owner.id, task_id=task.id)
    repository.submit(request)

    with pytest.raises(TerminalRunRepositoryError) as missing_worker:
        repository.transition(
            run_id=request.submission.selector.run_id,
            actor_user_id=owner.id,
            target=TerminalRunStatus.CLAIMED,
            changed_at=_NOW,
        )
    assert missing_worker.value.reason_code == "WORKER_ID_REQUIRED"

    other_user = get_user_model().objects.create_user(username=f"tar-transition-{uuid4().hex[:8]}")
    assert (
        repository.transition(
            run_id=request.submission.selector.run_id,
            actor_user_id=other_user.id,
            target=TerminalRunStatus.CANCEL_REQUESTED,
            changed_at=_NOW,
        )
        is None
    )

    claimed = repository.transition(
        run_id=request.submission.selector.run_id,
        actor_user_id=owner.id,
        target=TerminalRunStatus.CLAIMED,
        worker_id="worker-transition",
        changed_at=_NOW,
    )
    assert claimed is not None
    assert claimed.dispatch_status is TerminalRunStatus.CLAIMED
    assert claimed.claimed_by == "worker-transition"
    running = repository.transition(
        run_id=request.submission.selector.run_id,
        actor_user_id=owner.id,
        target=TerminalRunStatus.RUNNING,
        changed_at=_NOW,
    )
    assert running is not None
    assert running.dispatch_status is TerminalRunStatus.RUNNING

    with pytest.raises(TerminalRunRepositoryError) as invalid:
        repository.transition(
            run_id=request.submission.selector.run_id,
            actor_user_id=owner.id,
            target=TerminalRunStatus.QUEUED,
            changed_at=_NOW,
        )
    assert invalid.value.reason_code == "INVALID_RUN_TRANSITION"


def test_cancel_is_owner_scoped_and_idempotent(repository, owner, task):
    """Cancellation stores one timestamp and repeated requests are no-ops."""

    request = _request(owner_id=owner.id, task_id=task.id)
    repository.submit(request)
    requested_at = _NOW + timedelta(seconds=3)

    cancelled = repository.cancel(
        run_id=request.submission.selector.run_id,
        actor_user_id=owner.id,
        requested_at=requested_at,
    )
    assert cancelled is not None
    assert cancelled.dispatch_status is TerminalRunStatus.CANCEL_REQUESTED
    assert cancelled.cancel_requested_at == requested_at

    replay = repository.cancel(
        run_id=request.submission.selector.run_id,
        actor_user_id=owner.id,
        requested_at=requested_at + timedelta(seconds=10),
    )
    assert replay == cancelled
    row = TerminalAgentRunModel.objects.get(run_id=request.submission.selector.run_id)
    assert row.cancel_requested_at == requested_at


def test_heartbeat_rejects_wrong_worker_and_time_rewind(repository, owner, task):
    """Only the current worker can advance a non-terminal lease heartbeat."""

    request = _request(owner_id=owner.id, task_id=task.id)
    repository.submit(request)
    repository.claim(
        run_id=request.submission.selector.run_id,
        worker_id="worker-heartbeat",
        claimed_at=_NOW,
    )

    assert (
        repository.heartbeat(
            run_id=request.submission.selector.run_id,
            worker_id="other-worker",
            heartbeat_at=_NOW + timedelta(seconds=1),
        )
        is None
    )
    refreshed = repository.heartbeat(
        run_id=request.submission.selector.run_id,
        worker_id="worker-heartbeat",
        heartbeat_at=_NOW + timedelta(seconds=5),
    )
    assert refreshed is not None
    assert refreshed.heartbeat_at == _NOW + timedelta(seconds=5)

    with pytest.raises(TerminalRunRepositoryError) as rewind:
        repository.heartbeat(
            run_id=request.submission.selector.run_id,
            worker_id="worker-heartbeat",
            heartbeat_at=_NOW + timedelta(seconds=4),
        )
    assert rewind.value.reason_code == "HEARTBEAT_REWIND"


def test_append_event_rejects_a_worker_after_reaper_invalidates_its_lease(
    repository,
    owner,
    task,
):
    """An orphaned delivery cannot append replay data after lease loss."""

    request = _request(owner_id=owner.id, task_id=task.id, suffix="stale-event")
    repository.submit(request)
    worker_id = "worker-stale-event"
    repository.claim(
        run_id=request.submission.selector.run_id, worker_id=worker_id, claimed_at=_NOW
    )

    assert (
        repository.reap_stale(
            stale_before=_NOW + timedelta(seconds=1),
            reaped_at=_NOW + timedelta(seconds=2),
        )
        == 1
    )
    assert (
        repository.append_event(
            run_id=request.submission.selector.run_id,
            worker_id=worker_id,
            event_type="run.progress",
            data={"stage": "must-not-append"},
            occurred_at=_NOW + timedelta(seconds=3),
        )
        is None
    )


def test_stale_worker_cannot_heartbeat_or_finish_after_reaper_invalidates_lease(
    repository,
    owner,
    task,
):
    """An orphaned delivery cannot refresh or finalize its invalidated lease."""

    request = _request(owner_id=owner.id, task_id=task.id, suffix="stale-lease")
    repository.submit(request)
    worker_id = "worker-stale-lease"
    repository.claim(
        run_id=request.submission.selector.run_id, worker_id=worker_id, claimed_at=_NOW
    )

    assert (
        repository.reap_stale(
            stale_before=_NOW + timedelta(seconds=1),
            reaped_at=_NOW + timedelta(seconds=2),
        )
        == 1
    )
    assert (
        repository.heartbeat(
            run_id=request.submission.selector.run_id,
            worker_id=worker_id,
            heartbeat_at=_NOW + timedelta(seconds=3),
        )
        is None
    )
    assert (
        repository.mark_finished(
            run_id=request.submission.selector.run_id,
            worker_id=worker_id,
            status=TerminalRunStatus.FAILED,
            finished_at=_NOW + timedelta(seconds=4),
            error_code="terminal_agent_execution_failed",
        )
        is None
    )


def test_get_worker_input_rebuilds_authority_from_owner_projection(repository, owner, task):
    """Worker authorization comes from the current User/Profile projection."""

    _configure_owner_profile(owner, mcp_enabled=True)
    _configure_terminal_payload(task, provider_ref="system-default", model="test-model")
    request = _request(owner_id=owner.id, task_id=task.id, suffix="authority-valid")
    repository.submit(request)

    worker_input = repository.get_worker_input(
        run_id=request.submission.selector.run_id,
        task_id=task.id,
    )

    assert worker_input is not None
    assert worker_input.actor_user_id == owner.id
    assert worker_input.username == owner.username
    assert worker_input.user_role == "owner"
    assert worker_input.user_is_admin is False
    assert worker_input.mcp_enabled is True
    assert worker_input.provider_ref == "system-default"


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("user_role", "admin"),
        ("user_is_admin", True),
        ("mcp_enabled", False),
    ],
)
def test_get_worker_input_rejects_forged_authority_fields(
    repository,
    owner,
    task,
    field_name,
    forged_value,
):
    """Serialized identity facts cannot elevate or disable the owner."""

    _configure_owner_profile(owner, mcp_enabled=True)
    _configure_terminal_payload(task, **{field_name: forged_value})
    request = _request(owner_id=owner.id, task_id=task.id, suffix=f"authority-{field_name}")
    repository.submit(request)

    with pytest.raises(TerminalRunRepositoryError) as error:
        repository.get_worker_input(run_id=request.submission.selector.run_id, task_id=task.id)

    assert error.value.reason_code == "TERMINAL_TASK_AUTHORITY_MISMATCH"


def test_get_worker_input_fails_closed_without_authority_profile(repository, owner, task):
    """A missing account projection is not silently downgraded to read-only."""

    AccountProfileModel.objects.filter(user=owner).delete()
    _configure_terminal_payload(task)
    request = _request(owner_id=owner.id, task_id=task.id, suffix="authority-missing")
    repository.submit(request)

    with pytest.raises(TerminalRunRepositoryError) as error:
        repository.get_worker_input(run_id=request.submission.selector.run_id, task_id=task.id)

    assert error.value.reason_code == "TERMINAL_TASK_AUTHORITY_UNAVAILABLE"


def test_queue_summary_separates_owner_and_global_counts(repository, owner, task):
    """Queue observations expose owner counts without leaking run identities."""

    other_user = get_user_model().objects.create_user(username=f"tar-summary-{uuid4().hex[:8]}")
    other_task = AgentTaskModel.objects.create(
        request_id=f"tar-task-{uuid4().hex[:20]}",
        task_domain=TaskDomain.RESEARCH.value,
        task_type="terminal_summary_test",
        status=TaskStatus.DRAFT.value,
        input_payload={"summary": "test"},
        created_by=other_user,
    )
    owner_request = _request(owner_id=owner.id, task_id=task.id, suffix="summary-owner")
    other_request = _request(owner_id=other_user.id, task_id=other_task.id, suffix="summary-other")
    repository.submit(owner_request)
    repository.submit(other_request)
    repository.claim(
        run_id=owner_request.submission.selector.run_id,
        worker_id="worker-summary",
        claimed_at=_NOW,
    )

    owner_summary = repository.queue_summary(actor_user_id=owner.id)
    assert owner_summary.user_active == 1
    assert owner_summary.user_queued == 0
    assert owner_summary.global_active == 1
    assert owner_summary.global_queued == 1
    assert owner_summary.worker_ready is False

    other_summary = repository.queue_summary(actor_user_id=other_user.id)
    assert other_summary.user_active == 0
    assert other_summary.user_queued == 1
    assert other_summary.global_active == 1
    assert other_summary.global_queued == 1


def test_repository_source_has_no_runtime_dispatch_dependency():
    """The repository foundation cannot silently enable the worker runtime."""

    from pathlib import Path

    source = Path("apps/agent_runtime/infrastructure/terminal_agent_run_repository.py").read_text(
        encoding="utf-8"
    )
    assert "celery" not in source.casefold()
    assert "OpenAIAgentsTerminalService" not in source
    assert "redis" not in source.casefold()


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL first-winner evidence requires explicit disposable test settings",
)
def test_postgresql_concurrent_claim_has_one_winner(repository, owner, task):
    """PostgreSQL row locking permits exactly one concurrent claimant."""

    request = _request(owner_id=owner.id, task_id=task.id)
    repository.submit(request)
    barrier = Barrier(2)

    def _claim_in_worker(worker_id: str):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            result = TerminalAgentRunRepository().claim(
                run_id=request.submission.selector.run_id,
                worker_id=worker_id,
                claimed_at=_NOW,
            )
            return result.claimed_by if result is not None else None
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result(timeout=15)
            for future in (
                executor.submit(_claim_in_worker, "worker-a"),
                executor.submit(_claim_in_worker, "worker-b"),
            )
        )

    assert sorted(value is not None for value in results) == [False, True]


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL rollback visibility evidence requires an explicit PostgreSQL backend",
)
def test_postgresql_outer_rollback_is_not_visible_to_second_connection(repository, owner, task):
    """A second connection never observes a run whose admitting transaction rolls back."""

    request = _request(owner_id=owner.id, task_id=task.id, suffix="rollback-pg")
    inserted = Event()
    inspected = Event()
    release_rollback = Event()
    observations: list[bool] = []

    def _admit_then_rollback() -> None:
        """Insert inside an outer transaction and roll it back after inspection."""

        close_old_connections()
        try:
            with transaction.atomic():
                repository.submit(request)
                inserted.set()
                assert inspected.wait(timeout=10)
                assert release_rollback.wait(timeout=10)
                raise RuntimeError("TAR-02 PostgreSQL rollback evidence sentinel")
        except RuntimeError as error:
            assert str(error) == "TAR-02 PostgreSQL rollback evidence sentinel"
        finally:
            connections["default"].close()

    def _observe_from_second_connection() -> None:
        """Observe uncommitted and post-rollback visibility from another connection."""

        close_old_connections()
        try:
            assert inserted.wait(timeout=10)
            observations.append(
                TerminalAgentRunModel.objects.filter(
                    run_id=request.submission.selector.run_id
                ).exists()
            )
            inspected.set()
            # Release the admitting transaction only after this connection has
            # observed the uncommitted row as invisible.
            release_rollback.set()
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        admission = executor.submit(_admit_then_rollback)
        observer = executor.submit(_observe_from_second_connection)
        observer.result(timeout=20)
        admission.result(timeout=20)

    observations.append(
        TerminalAgentRunModel.objects.filter(run_id=request.submission.selector.run_id).exists()
    )
    assert observations == [False, False]
