"""Regression tests for Terminal Agent distributed execution leases."""

from contextlib import AbstractContextManager
from threading import Barrier, Event, Lock, Thread

import pytest
from django.core.cache.backends.locmem import LocMemCache

from apps.agent_runtime.application.terminal_agent import (
    TerminalAgentBusyError,
    TerminalAgentChatRequestDTO,
)
from apps.agent_runtime.infrastructure.terminal_agent_execution_guard import (
    CacheTerminalAgentExecutionGuard,
)


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def add(self, key: str, value: str, timeout: int) -> bool:
        del timeout
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> bool:
        return self.values.pop(key, None) is not None


def _request(*, user_id: int = 7) -> TerminalAgentChatRequestDTO:
    return TerminalAgentChatRequestDTO(
        message="health",
        session_id=f"session-{user_id}",
        user_id=user_id,
        username=f"user-{user_id}",
        user_role="admin",
        user_is_admin=True,
        mcp_enabled=True,
    )


def _enter(
    guard: CacheTerminalAgentExecutionGuard,
    request: TerminalAgentChatRequestDTO,
) -> AbstractContextManager[None]:
    lease = guard.acquire(request)
    lease.__enter__()
    return lease


def test_guard_rejects_duplicate_request_for_same_user_and_releases_lease():
    cache = _MemoryCache()
    guard = CacheTerminalAgentExecutionGuard(cache_backend=cache, max_concurrency=2)
    first = _enter(guard, _request())

    with pytest.raises(TerminalAgentBusyError):
        with guard.acquire(_request()):
            pass

    first.__exit__(None, None, None)
    with guard.acquire(_request()):
        pass


def test_guard_enforces_global_concurrency_limit_across_users():
    cache = _MemoryCache()
    guard = CacheTerminalAgentExecutionGuard(cache_backend=cache, max_concurrency=1)
    first = _enter(guard, _request(user_id=7))

    with pytest.raises(TerminalAgentBusyError):
        with guard.acquire(_request(user_id=8)):
            pass

    first.__exit__(None, None, None)
    with guard.acquire(_request(user_id=8)):
        pass


def test_guard_fails_closed_when_cache_is_unavailable():
    cache = _MemoryCache()

    def broken_add(_key: str, _value: str, _timeout: int) -> bool:
        raise ConnectionError("redis unavailable")

    cache.add = broken_add  # type: ignore[method-assign]
    guard = CacheTerminalAgentExecutionGuard(cache_backend=cache, max_concurrency=1)

    with pytest.raises(TerminalAgentBusyError):
        with guard.acquire(_request()):
            pass


def test_guard_releases_leases_when_guarded_operation_raises():
    guard = CacheTerminalAgentExecutionGuard(
        cache_backend=_MemoryCache(),
        max_concurrency=1,
    )

    with pytest.raises(RuntimeError, match="operation failed"):
        with guard.acquire(_request()):
            raise RuntimeError("operation failed")

    with guard.acquire(_request()):
        pass


def test_guard_does_not_delete_a_new_owner_lease_after_old_lease_exits():
    cache = _MemoryCache()
    guard = CacheTerminalAgentExecutionGuard(cache_backend=cache, max_concurrency=1)
    first = _enter(guard, _request())
    renewed_values = dict.fromkeys(cache.values, "new-owner-token")
    cache.values.update(renewed_values)

    first.__exit__(None, None, None)

    assert cache.values == renewed_values


def test_independent_guards_share_django_cache_and_admit_only_one_concurrent_run():
    cache = LocMemCache("terminal-agent-concurrency-test", {})
    barrier = Barrier(2)
    winner_started = Event()
    loser_finished = Event()
    release_winner = Event()
    results: list[str] = []
    results_lock = Lock()

    def execute(user_id: int) -> None:
        guard = CacheTerminalAgentExecutionGuard(cache_backend=cache, max_concurrency=1)
        barrier.wait(timeout=2)
        try:
            with guard.acquire(_request(user_id=user_id)):
                with results_lock:
                    results.append("entered")
                winner_started.set()
                release_winner.wait(timeout=2)
        except TerminalAgentBusyError:
            with results_lock:
                results.append("busy")
            loser_finished.set()

    workers = [Thread(target=execute, args=(user_id,)) for user_id in (7, 8)]
    for worker in workers:
        worker.start()

    assert winner_started.wait(timeout=2)
    assert loser_finished.wait(timeout=2)
    release_winner.set()
    for worker in workers:
        worker.join(timeout=2)

    assert results.count("entered") == 1
    assert results.count("busy") == 1
    assert all(not worker.is_alive() for worker in workers)
