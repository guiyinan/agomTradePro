"""Ownership and handoff regression coverage for Alpha operational locks."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from django.core.cache import cache

from apps.alpha.application import ops_locks, ops_use_cases
from apps.alpha.application.ops_locks import (
    acquire_dashboard_alpha_refresh_pending_lock,
    promote_dashboard_alpha_refresh_task_lock,
    release_dashboard_alpha_refresh_lock,
    resolve_dashboard_alpha_refresh_lock,
)
from apps.alpha.application.ops_use_cases import TriggerGeneralInferenceUseCase


@pytest.fixture(autouse=True)
def _isolated_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


class _PendingResult:
    """Minimal non-terminal Celery result used by lock inspection tests."""

    state = "STARTED"

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def ready(self) -> bool:
        return False


class _ReadyResult:
    """Minimal terminal Celery result used to trigger owner handoff."""

    state = "SUCCESS"

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def ready(self) -> bool:
        return True


def test_stale_owner_cannot_promote_or_release_successor_generation() -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:test:2026-07-28:20"
    first_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"universe_id": "first"},
    )
    assert first_owner is not None
    assert release_dashboard_alpha_refresh_lock(
        lock_key,
        owner_token=first_owner,
    )

    second_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"universe_id": "second"},
    )
    assert second_owner is not None
    assert second_owner != first_owner

    assert not promote_dashboard_alpha_refresh_task_lock(
        lock_key,
        owner_token=first_owner,
        task_id="stale-task",
    )
    assert not release_dashboard_alpha_refresh_lock(
        lock_key,
        owner_token=first_owner,
    )
    assert resolve_dashboard_alpha_refresh_lock(lock_key) == {
        "universe_id": "second",
        "status": "running",
        "mode": "async",
        "task_id": None,
        "task_state": "PENDING",
    }

    assert promote_dashboard_alpha_refresh_task_lock(
        lock_key,
        owner_token=second_owner,
        task_id="current-task",
    )
    assert resolve_dashboard_alpha_refresh_lock(
        lock_key,
        async_result_cls=_PendingResult,
    ) == {
        "universe_id": "second",
        "status": "running",
        "mode": "async",
        "task_id": "current-task",
        "task_state": "STARTED",
    }


def test_completed_owner_hands_off_without_exposing_owner_token() -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:complete:2026-07-28:20"
    first_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"scope_hash": "first-scope"},
    )
    assert first_owner is not None
    assert promote_dashboard_alpha_refresh_task_lock(
        lock_key,
        owner_token=first_owner,
        task_id="completed-task",
    )

    assert (
        resolve_dashboard_alpha_refresh_lock(
            lock_key,
            async_result_cls=_ReadyResult,
        )
        is None
    )
    second_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"scope_hash": "second-scope"},
    )
    assert second_owner is not None
    assert second_owner != first_owner
    visible = resolve_dashboard_alpha_refresh_lock(lock_key)
    assert visible is not None
    assert visible["scope_hash"] == "second-scope"
    assert "owner_token" not in visible
    assert not release_dashboard_alpha_refresh_lock(
        lock_key,
        owner_token=first_owner,
    )


def test_completed_legacy_lock_waits_for_original_ttl_instead_of_unsafe_delete() -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:legacy:2026-07-28:20"
    meta_key = f"{lock_key}:meta"
    cache.set(lock_key, "legacy-completed-task", timeout=60)
    cache.set(meta_key, {"scope_hash": "legacy-scope"}, timeout=60)

    assert (
        resolve_dashboard_alpha_refresh_lock(
            lock_key,
            async_result_cls=_ReadyResult,
        )
        is None
    )
    assert cache.get(lock_key) == "legacy-completed-task"
    assert cache.get(meta_key) == {"scope_hash": "legacy-scope"}


def test_expired_pending_owner_can_be_replaced_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:expired:2026-07-28:20"
    monkeypatch.setattr(ops_locks.time, "time", lambda: 100.0)
    first_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"generation": 1},
        timeout=1,
    )
    assert first_owner is not None

    monkeypatch.setattr(ops_locks.time, "time", lambda: 102.0)
    second_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"generation": 2},
        timeout=10,
    )
    assert second_owner is not None
    assert second_owner != first_owner
    assert not promote_dashboard_alpha_refresh_task_lock(
        lock_key,
        owner_token=first_owner,
        task_id="late-task",
    )
    assert resolve_dashboard_alpha_refresh_lock(lock_key)["generation"] == 2


def test_released_generation_has_exactly_one_concurrent_successor() -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:race:2026-07-28:20"
    first_owner = acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta={"generation": 1},
    )
    assert first_owner is not None
    assert release_dashboard_alpha_refresh_lock(
        lock_key,
        owner_token=first_owner,
    )

    def _contend(generation: int) -> ops_locks.LockOwnerToken | None:
        return acquire_dashboard_alpha_refresh_pending_lock(
            lock_key,
            meta={"generation": generation},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        owners = list(executor.map(_contend, [2, 3]))

    winners = [owner for owner in owners if owner is not None]
    assert len(winners) == 1
    visible = resolve_dashboard_alpha_refresh_lock(lock_key)
    assert visible is not None
    assert visible["generation"] in (2, 3)


@pytest.mark.parametrize("timeout", [True, False, 0, -1])
def test_invalid_timeout_never_publishes_a_lock(timeout: int) -> None:
    lock_key = "dashboard:alpha_refresh_lock:general:invalid:2026-07-28:20"
    with pytest.raises(ValueError, match="positive integer"):
        acquire_dashboard_alpha_refresh_pending_lock(
            lock_key,
            meta={"scope": "invalid"},
            timeout=timeout,
        )
    assert cache.get(lock_key) is None


def test_tracking_failure_after_dispatch_does_not_release_running_task_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[str] = []

    class _QueuedTask:
        id = "queued-before-tracking-failure"

    class _TaskGateway:
        @staticmethod
        def delay(universe_id: str, trade_date: str, top_n: int) -> _QueuedTask:
            del trade_date, top_n
            dispatched.append(universe_id)
            return _QueuedTask()

    def _fail_tracking(**kwargs: object) -> None:
        del kwargs
        raise OSError("tracking database unavailable")

    def _resolve_pending(lock_key: str) -> dict[str, object] | None:
        return resolve_dashboard_alpha_refresh_lock(
            lock_key,
            async_result_cls=_PendingResult,
        )

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", _TaskGateway)
    monkeypatch.setattr(ops_use_cases, "record_pending_task", _fail_tracking)
    monkeypatch.setattr(
        ops_use_cases,
        "resolve_dashboard_alpha_refresh_lock",
        _resolve_pending,
    )
    use_case = TriggerGeneralInferenceUseCase()
    request_kwargs = {
        "trade_date": date(2026, 7, 28),
        "top_n": 20,
        "universe_id": "csi300",
    }

    with pytest.raises(OSError, match="tracking database unavailable"):
        use_case.execute(**request_kwargs)
    conflict = use_case.execute(**request_kwargs)

    assert conflict["success"] is False
    assert conflict["task_id"] == _QueuedTask.id
    assert dispatched == ["csi300"]


def test_dispatch_failure_releases_only_its_owner_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class _QueuedTask:
        id = "queued-after-dispatch-retry"

    class _TaskGateway:
        @staticmethod
        def delay(universe_id: str, trade_date: str, top_n: int) -> _QueuedTask:
            del universe_id, trade_date, top_n
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("broker unavailable")
            return _QueuedTask()

    monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", _TaskGateway)
    monkeypatch.setattr(ops_use_cases, "record_pending_task", lambda **kwargs: None)
    use_case = TriggerGeneralInferenceUseCase()
    request_kwargs = {
        "trade_date": date(2026, 7, 28),
        "top_n": 30,
        "universe_id": "csi500",
    }

    with pytest.raises(ConnectionError, match="broker unavailable"):
        use_case.execute(**request_kwargs)
    result = use_case.execute(**request_kwargs)

    assert result["success"] is True
    assert result["task_id"] == _QueuedTask.id
    assert attempts == 2
