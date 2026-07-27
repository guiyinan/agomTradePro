"""Atomic decision-execution repository state-transition contracts."""

from __future__ import annotations

from types import TracebackType

from apps.events.infrastructure import repositories as module


class _AtomicProbe:
    def __init__(self) -> None:
        self.exit_exception_types: list[type[BaseException] | None] = []

    def __enter__(self) -> _AtomicProbe:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        self.exit_exception_types.append(exc_type)
        return False


class _RequestRepository:
    def __init__(self, *, executed: bool = True, failed: bool = True) -> None:
        self.executed = executed
        self.failed = failed
        self.calls: list[str] = []

    def update_execution_status_to_executed(
        self,
        request_id: str,
        execution_ref: dict[str, object] | None,
    ) -> bool:
        del execution_ref
        self.calls.append(f"executed:{request_id}")
        return self.executed

    def update_execution_status_to_failed(self, request_id: str) -> bool:
        self.calls.append(f"failed:{request_id}")
        return self.failed


class _CandidateRepository:
    def __init__(self, *, executed: bool = True, failed: bool = True) -> None:
        self.executed = executed
        self.failed = failed
        self.calls: list[str] = []

    def update_status_to_executed(self, candidate_id: str) -> bool:
        self.calls.append(f"executed:{candidate_id}")
        return self.executed

    def update_execution_status_to_failed(self, candidate_id: str) -> bool:
        self.calls.append(f"failed:{candidate_id}")
        return self.failed


def test_executed_sync_raises_inside_atomic_block_on_partial_write(monkeypatch) -> None:
    """A false candidate write reaches transaction exit as an exception for rollback."""

    atomic = _AtomicProbe()
    request_repository = _RequestRepository()
    candidate_repository = _CandidateRepository(executed=False)
    monkeypatch.setattr(module.transaction, "atomic", lambda: atomic)
    repository = module.DecisionExecutionSyncRepository(
        request_repository,
        candidate_repository,
    )

    assert not repository.sync_executed(
        request_id="request-1",
        execution_ref={"broker": "simulated"},
        candidate_id="candidate-1",
    )
    assert atomic.exit_exception_types == [module._SynchronizationRejected]
    assert request_repository.calls == ["executed:request-1"]
    assert candidate_repository.calls == ["executed:candidate-1"]


def test_executed_sync_stops_before_candidate_when_request_write_fails(monkeypatch) -> None:
    """A missing request update cannot advance its Alpha candidate."""

    atomic = _AtomicProbe()
    request_repository = _RequestRepository(executed=False)
    candidate_repository = _CandidateRepository()
    monkeypatch.setattr(module.transaction, "atomic", lambda: atomic)
    repository = module.DecisionExecutionSyncRepository(
        request_repository,
        candidate_repository,
    )

    assert not repository.sync_executed(
        request_id="request-1",
        execution_ref=None,
        candidate_id="candidate-1",
    )
    assert atomic.exit_exception_types == [module._SynchronizationRejected]
    assert candidate_repository.calls == []


def test_failed_sync_commits_only_when_both_writes_succeed(monkeypatch) -> None:
    """Successful failure synchronization leaves the atomic block normally."""

    atomic = _AtomicProbe()
    request_repository = _RequestRepository()
    candidate_repository = _CandidateRepository()
    monkeypatch.setattr(module.transaction, "atomic", lambda: atomic)
    repository = module.DecisionExecutionSyncRepository(
        request_repository,
        candidate_repository,
    )

    assert repository.sync_failed(
        request_id="request-1",
        candidate_id="candidate-1",
        error_message="broker rejected token=secret",
    )
    assert atomic.exit_exception_types == [None]
    assert request_repository.calls == ["failed:request-1"]
    assert candidate_repository.calls == ["failed:candidate-1"]
