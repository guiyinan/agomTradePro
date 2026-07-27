"""Shared lock helpers for Alpha/Qlib operational actions."""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from datetime import date
from typing import Any, Literal, NewType, Protocol, TypedDict, cast

from celery.result import AsyncResult
from django.core.cache import cache

from apps.alpha.application.pool_resolver import ResolvedAlphaPool

ALPHA_REFRESH_LOCK_TTL_SECONDS = 600
QLIB_REFRESH_LOCK_TTL_SECONDS = 1800

LockOwnerToken = NewType("LockOwnerToken", str)
_LockPhase = Literal["pending", "async", "sync", "released", "completed"]

_OWNER_TOKEN_PREFIX = "alpha-lock-owner-v2:"
_LOCK_CHAIN_TTL_SECONDS = 24 * 60 * 60
_MAX_LOCK_CHAIN_DEPTH = 64

_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY = "alpha:ops:dashboard_refresh_lock_registry"
_INFERENCE_BATCH_REGISTRY_KEY = "alpha:ops:inference_batch_lock_registry"
_QLIB_DATA_REFRESH_REGISTRY_KEY = "alpha:ops:qlib_data_refresh_lock_registry"


class _AsyncResultLike(Protocol):
    """Minimal Celery result contract needed for lock inspection."""

    state: str

    def ready(self) -> bool:
        """Return whether the asynchronous task reached a terminal state."""


class _AsyncResultFactory(Protocol):
    """Construct a task result handle from a Celery task id."""

    def __call__(self, task_id: str) -> _AsyncResultLike:
        """Return a task result handle."""


class _LockState(TypedDict):
    """Owner-specific mutable state behind an immutable lock claim."""

    owner_token: str
    phase: _LockPhase
    task_id: str | None
    lease_expires_at: float
    meta: dict[str, Any]


_DEFAULT_ASYNC_RESULT_FACTORY = cast(_AsyncResultFactory, AsyncResult)


def _lock_meta_key(lock_key: str) -> str:
    """Return the legacy v1 metadata key during rolling upgrades."""

    return f"{lock_key}:meta"


def _stable_fragment(value: str) -> str:
    """Return a bounded cache-safe digest for one lock scope."""

    digest = hashlib.blake2s(value.encode("utf-8"), digest_size=8).hexdigest()
    return digest[:16]


def _owner_state_key(lock_key: str, owner_token: LockOwnerToken) -> str:
    """Return the private state key for one immutable lock owner."""

    return (
        "alpha:ops:lock-state:v2:"
        f"{_stable_fragment(lock_key)}:{_stable_fragment(str(owner_token))}"
    )


def _successor_key(lock_key: str, owner_token: LockOwnerToken) -> str:
    """Return the atomic handoff slot owned by one lock generation."""

    return (
        "alpha:ops:lock-successor:v2:"
        f"{_stable_fragment(lock_key)}:{_stable_fragment(str(owner_token))}"
    )


def _new_owner_token() -> LockOwnerToken:
    """Create a process-independent opaque lock ownership token."""

    return LockOwnerToken(f"{_OWNER_TOKEN_PREFIX}{uuid.uuid4().hex}")


def _coerce_owner_token(value: object) -> LockOwnerToken | None:
    """Narrow an untrusted cache value to a v2 owner token."""

    if not isinstance(value, str) or not value.startswith(_OWNER_TOKEN_PREFIX):
        return None
    suffix = value.removeprefix(_OWNER_TOKEN_PREFIX)
    if len(suffix) != 32:
        return None
    try:
        uuid.UUID(hex=suffix)
    except ValueError:
        return None
    return LockOwnerToken(value)


def _validated_timeout(timeout: int) -> int:
    """Require a positive non-boolean cache lease duration."""

    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("lock timeout must be a positive integer")
    return timeout


def _coerce_meta(value: object) -> dict[str, Any] | None:
    """Narrow cached lock metadata to a string-keyed mapping."""

    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        return None
    return dict(value)


def _coerce_lock_state(
    value: object,
    *,
    expected_owner: LockOwnerToken,
) -> _LockState | None:
    """Validate owner-specific cache state before operational use."""

    if not isinstance(value, dict):
        return None
    owner_token = value.get("owner_token")
    phase = value.get("phase")
    task_id = value.get("task_id")
    lease_expires_at = value.get("lease_expires_at")
    meta = _coerce_meta(value.get("meta"))
    if owner_token != str(expected_owner):
        return None
    if phase not in ("pending", "async", "sync", "released", "completed"):
        return None
    if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
        return None
    if isinstance(lease_expires_at, bool) or not isinstance(lease_expires_at, int | float):
        return None
    normalized_expiry = float(lease_expires_at)
    if not math.isfinite(normalized_expiry):
        return None
    if meta is None:
        return None
    return {
        "owner_token": str(expected_owner),
        "phase": cast(_LockPhase, phase),
        "task_id": task_id,
        "lease_expires_at": normalized_expiry,
        "meta": meta,
    }


def _build_lock_state(
    *,
    owner_token: LockOwnerToken,
    phase: _LockPhase,
    timeout: int,
    meta: dict[str, Any],
    task_id: str | None = None,
) -> _LockState:
    """Build validated owner-specific lock state with an absolute lease."""

    return {
        "owner_token": str(owner_token),
        "phase": phase,
        "task_id": task_id,
        "lease_expires_at": time.time() + _validated_timeout(timeout),
        "meta": dict(meta),
    }


def _read_owner_state(lock_key: str, owner_token: LockOwnerToken) -> _LockState | None:
    """Read and validate the state belonging to one owner token."""

    return _coerce_lock_state(
        cache.get(_owner_state_key(lock_key, owner_token)),
        expected_owner=owner_token,
    )


def _write_owner_state(
    lock_key: str,
    owner_token: LockOwnerToken,
    state: _LockState,
) -> None:
    """Persist owner-specific state without mutating another generation."""

    cache.set(
        _owner_state_key(lock_key, owner_token),
        state,
        timeout=_LOCK_CHAIN_TTL_SECONDS,
    )


def _latest_owner_token(
    lock_key: str,
    *,
    renew_chain: bool = False,
) -> LockOwnerToken | None:
    """Follow immutable handoff links to the current lock owner."""

    current = _coerce_owner_token(cache.get(lock_key))
    if current is None:
        return None
    seen: set[LockOwnerToken] = {current}
    traversed_links: list[str] = []
    for _index in range(_MAX_LOCK_CHAIN_DEPTH):
        successor_key = _successor_key(lock_key, current)
        successor_value = cache.get(successor_key)
        if successor_value is None:
            if renew_chain:
                cache.touch(lock_key, timeout=_LOCK_CHAIN_TTL_SECONDS)
                for traversed_link in traversed_links:
                    cache.touch(traversed_link, timeout=_LOCK_CHAIN_TTL_SECONDS)
            return current
        successor = _coerce_owner_token(successor_value)
        if successor is None or successor in seen:
            return current
        traversed_links.append(successor_key)
        seen.add(successor)
        current = successor
    return current


def _state_is_active(state: _LockState | None) -> bool:
    """Return whether one owner state still holds an active lease."""

    return bool(
        state is not None
        and state["phase"] in ("pending", "async", "sync")
        and state["lease_expires_at"] > time.time()
    )


def _register_lock(registry_key: str, lock_key: str) -> None:
    """Register one lock key for operations-page discovery."""

    cached_registry = cache.get(registry_key)
    registry = (
        list(cached_registry)
        if isinstance(cached_registry, list)
        and all(isinstance(item, str) for item in cached_registry)
        else []
    )
    if lock_key not in registry:
        registry.append(lock_key)
    cache.set(registry_key, registry, timeout=_LOCK_CHAIN_TTL_SECONDS)


def build_dashboard_alpha_refresh_lock_key(
    *,
    alpha_scope: str,
    target_date: date,
    top_n: int,
    raw_universe_id: str,
    resolved_pool: ResolvedAlphaPool | None = None,
    scope_hash: str | None = None,
) -> str:
    """Build a stable lock key for one dashboard/ops alpha refresh scope."""
    resolved_scope_hash = scope_hash
    if resolved_scope_hash is None and resolved_pool is not None:
        resolved_scope_hash = getattr(getattr(resolved_pool, "scope", None), "scope_hash", None)
    scope_key = resolved_scope_hash or raw_universe_id
    return (
        "dashboard:alpha_refresh_lock:"
        f"{alpha_scope}:{scope_key}:{target_date.isoformat()}:{top_n}"
    )


def build_dashboard_alpha_refresh_metadata(
    *,
    alpha_scope: str,
    target_date: date,
    top_n: int,
    universe_id: str,
    portfolio_id: int | None,
    pool_mode: str,
    scope_hash: str | None = None,
) -> dict[str, Any]:
    """Return lock metadata used by dashboard and alpha ops pages."""
    return {
        "lock_type": "dashboard_alpha_refresh",
        "alpha_scope": alpha_scope,
        "requested_trade_date": target_date.isoformat(),
        "top_n": top_n,
        "universe_id": universe_id,
        "portfolio_id": portfolio_id,
        "pool_mode": pool_mode,
        "scope_hash": scope_hash,
    }


def build_inference_batch_lock_key(
    *,
    mode: str,
    target_date: date,
    top_n: int,
    descriptor: str,
) -> str:
    """Build a stable lock key for one alpha inference batch operation."""
    return (
        "alpha:ops:inference_batch_lock:"
        f"{mode}:{target_date.isoformat()}:{top_n}:{_stable_fragment(descriptor)}"
    )


def build_qlib_data_refresh_lock_key(
    *,
    mode: str,
    target_date: date,
    lookback_days: int,
    descriptor: str,
) -> str:
    """Build a stable lock key for one qlib data refresh operation."""
    return (
        "alpha:ops:qlib_data_refresh_lock:"
        f"{mode}:{target_date.isoformat()}:{lookback_days}:{_stable_fragment(descriptor)}"
    )


def _resolve_async_lock(
    *,
    lock_key: str,
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
    cleanup_stale: bool = True,
) -> dict[str, Any] | None:
    """Resolve v2 owner state or a rolling-upgrade v1 lock entry."""

    existing_lock = cache.get(lock_key)
    if existing_lock is None:
        return None

    root_owner = _coerce_owner_token(existing_lock)
    if root_owner is not None:
        owner_token = _latest_owner_token(lock_key)
        if owner_token is None:
            return None
        state = _read_owner_state(lock_key, owner_token)
        if not _state_is_active(state):
            return None
        assert state is not None
        meta = dict(state["meta"])
        if state["phase"] == "sync":
            return {
                **meta,
                "status": "running",
                "mode": "sync",
                "task_id": None,
                "task_state": "RUNNING",
            }
        if state["phase"] == "pending":
            return {
                **meta,
                "status": "running",
                "mode": "async",
                "task_id": None,
                "task_state": "PENDING",
            }
        task_id = state["task_id"]
        if task_id is None:
            return None
        try:
            task_result = async_result_cls(task_id)
            if task_result.ready():
                if cleanup_stale and _latest_owner_token(lock_key) == owner_token:
                    _write_owner_state(
                        lock_key,
                        owner_token,
                        _build_lock_state(
                            owner_token=owner_token,
                            phase="completed",
                            timeout=_LOCK_CHAIN_TTL_SECONDS,
                            meta=meta,
                            task_id=task_id,
                        ),
                    )
                return None
            task_state = str(task_result.state or "PENDING")
        except Exception:
            task_state = "UNKNOWN"
        return {
            **meta,
            "status": "running",
            "mode": "async",
            "task_id": task_id,
            "task_state": task_state,
        }

    legacy_meta = _coerce_meta(cache.get(_lock_meta_key(lock_key))) or {}
    if existing_lock == "__sync__":
        return {
            **legacy_meta,
            "status": "running",
            "mode": "sync",
            "task_id": None,
            "task_state": "RUNNING",
        }
    if existing_lock == "__pending__":
        return {
            **legacy_meta,
            "status": "running",
            "mode": "async",
            "task_id": None,
            "task_state": "PENDING",
        }

    task_id = str(existing_lock)
    try:
        task_result = async_result_cls(task_id)
        if task_result.ready():
            # V1 has no owner token, so conditional deletion is impossible.
            # Preserve the original TTL instead of letting a stale inspector
            # delete a v2 claim acquired immediately after physical removal.
            return None
        task_state = str(task_result.state or "PENDING")
    except Exception:
        task_state = "UNKNOWN"

    return {
        **legacy_meta,
        "status": "running",
        "mode": "async",
        "task_id": task_id,
        "task_state": task_state,
    }


def _acquire_pending_lock(
    *,
    registry_key: str,
    lock_key: str,
    meta: dict[str, Any],
    timeout: int,
) -> LockOwnerToken | None:
    """Acquire an immutable lock generation and return its ownership token."""

    normalized_timeout = _validated_timeout(timeout)
    if not lock_key.strip():
        raise ValueError("lock_key must be a non-empty string")
    normalized_meta = _coerce_meta(meta)
    if normalized_meta is None:
        raise ValueError("lock metadata must use string keys")

    owner_token = _new_owner_token()
    state_key = _owner_state_key(lock_key, owner_token)
    _write_owner_state(
        lock_key,
        owner_token,
        _build_lock_state(
            owner_token=owner_token,
            phase="pending",
            timeout=normalized_timeout,
            meta=normalized_meta,
        ),
    )

    existing_lock = cache.get(lock_key)
    if existing_lock is None:
        cache.add(lock_key, str(owner_token), timeout=_LOCK_CHAIN_TTL_SECONDS)
    elif _coerce_owner_token(existing_lock) is None:
        cache.delete(state_key)
        return None

    latest_owner = _latest_owner_token(lock_key, renew_chain=True)
    if latest_owner is None:
        cache.delete(state_key)
        return None
    if latest_owner != owner_token:
        if _state_is_active(_read_owner_state(lock_key, latest_owner)):
            cache.delete(state_key)
            return None
        cache.add(
            _successor_key(lock_key, latest_owner),
            str(owner_token),
            timeout=_LOCK_CHAIN_TTL_SECONDS,
        )

    if _latest_owner_token(lock_key, renew_chain=True) != owner_token:
        cache.delete(state_key)
        return None
    _register_lock(registry_key, lock_key)
    return owner_token


def _promote_async_lock(
    *,
    lock_key: str,
    owner_token: LockOwnerToken,
    task_id: str,
    timeout: int,
    meta_updates: dict[str, Any] | None = None,
) -> bool:
    """Promote only the still-current pending owner to a task or sync lease."""

    normalized_timeout = _validated_timeout(timeout)
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        raise ValueError("task_id must be a non-empty string")
    normalized_updates = _coerce_meta(meta_updates) if meta_updates is not None else {}
    if normalized_updates is None:
        raise ValueError("lock metadata updates must use string keys")
    if _latest_owner_token(lock_key) != owner_token:
        return False
    current_state = _read_owner_state(lock_key, owner_token)
    if (
        current_state is None
        or current_state["phase"] != "pending"
        or current_state["lease_expires_at"] <= time.time()
    ):
        return False
    meta = dict(current_state["meta"])
    meta.update(normalized_updates)
    is_sync = normalized_task_id == "__sync__"
    _write_owner_state(
        lock_key,
        owner_token,
        _build_lock_state(
            owner_token=owner_token,
            phase="sync" if is_sync else "async",
            timeout=normalized_timeout,
            meta=meta,
            task_id=None if is_sync else normalized_task_id,
        ),
    )
    return _latest_owner_token(lock_key) == owner_token


def _release_lock(*, lock_key: str, owner_token: LockOwnerToken) -> bool:
    """Release only the generation identified by the supplied owner token."""

    if _latest_owner_token(lock_key) != owner_token:
        return False
    current_state = _read_owner_state(lock_key, owner_token)
    meta = dict(current_state["meta"]) if current_state is not None else {}
    _write_owner_state(
        lock_key,
        owner_token,
        _build_lock_state(
            owner_token=owner_token,
            phase="released",
            timeout=_LOCK_CHAIN_TTL_SECONDS,
            meta=meta,
            task_id=current_state["task_id"] if current_state is not None else None,
        ),
    )
    return True


def _list_active_locks(
    *,
    registry_key: str,
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
    cleanup_stale: bool = True,
) -> list[dict[str, Any]]:
    """Resolve registered locks without trusting a malformed registry value."""

    active_items: list[dict[str, Any]] = []
    cached_registry = cache.get(registry_key)
    registry = (
        list(cached_registry)
        if isinstance(cached_registry, list)
        and all(isinstance(item, str) for item in cached_registry)
        else []
    )
    for lock_key in registry:
        lock_meta = _resolve_async_lock(
            lock_key=lock_key,
            async_result_cls=async_result_cls,
            cleanup_stale=cleanup_stale,
        )
        if lock_meta is None:
            continue
        active_items.append(lock_meta)
    active_items.sort(
        key=lambda item: (
            str(item.get("requested_trade_date") or ""),
            str(item.get("scope_hash") or item.get("universe_id") or ""),
        ),
        reverse=True,
    )
    return active_items


def resolve_dashboard_alpha_refresh_lock(
    lock_key: str,
    *,
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
) -> dict[str, Any] | None:
    """Return dashboard alpha refresh lock metadata with safe stale resolution."""
    return _resolve_async_lock(
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_dashboard_alpha_refresh_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
) -> LockOwnerToken | None:
    """Acquire a dashboard alpha refresh pending lock."""
    return _acquire_pending_lock(
        registry_key=_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        meta=meta,
        timeout=timeout,
    )


def promote_dashboard_alpha_refresh_task_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
    task_id: str,
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> bool:
    """Replace a pending dashboard alpha refresh lock with the Celery task id."""
    return _promote_async_lock(
        lock_key=lock_key,
        owner_token=owner_token,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_dashboard_alpha_refresh_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
) -> bool:
    """Release a dashboard alpha refresh lock and its metadata."""
    return _release_lock(lock_key=lock_key, owner_token=owner_token)


def list_active_dashboard_alpha_refresh_locks(
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
    *,
    cleanup_stale: bool = True,
) -> list[dict[str, Any]]:
    """Return current dashboard alpha refresh locks visible to the ops page."""
    return _list_active_locks(
        registry_key=_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY,
        async_result_cls=async_result_cls,
        cleanup_stale=cleanup_stale,
    )


def resolve_inference_batch_lock(
    lock_key: str,
    *,
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
) -> dict[str, Any] | None:
    """Resolve one alpha inference batch lock."""
    return _resolve_async_lock(
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_inference_batch_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
) -> LockOwnerToken | None:
    """Acquire a pending alpha inference batch lock."""
    return _acquire_pending_lock(
        registry_key=_INFERENCE_BATCH_REGISTRY_KEY,
        lock_key=lock_key,
        meta=meta,
        timeout=timeout,
    )


def promote_inference_batch_task_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
    task_id: str,
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> bool:
    """Replace a pending alpha inference batch lock with the Celery task id."""
    return _promote_async_lock(
        lock_key=lock_key,
        owner_token=owner_token,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_inference_batch_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
) -> bool:
    """Release an alpha inference batch lock."""
    return _release_lock(lock_key=lock_key, owner_token=owner_token)


def resolve_qlib_data_refresh_lock(
    lock_key: str,
    *,
    async_result_cls: _AsyncResultFactory = _DEFAULT_ASYNC_RESULT_FACTORY,
) -> dict[str, Any] | None:
    """Resolve one qlib data refresh lock."""
    return _resolve_async_lock(
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_qlib_data_refresh_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = QLIB_REFRESH_LOCK_TTL_SECONDS,
) -> LockOwnerToken | None:
    """Acquire a pending qlib data refresh lock."""
    return _acquire_pending_lock(
        registry_key=_QLIB_DATA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        meta=meta,
        timeout=timeout,
    )


def promote_qlib_data_refresh_task_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
    task_id: str,
    timeout: int = QLIB_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> bool:
    """Replace a pending qlib data refresh lock with the Celery task id."""
    return _promote_async_lock(
        lock_key=lock_key,
        owner_token=owner_token,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_qlib_data_refresh_lock(
    lock_key: str,
    *,
    owner_token: LockOwnerToken,
) -> bool:
    """Release a qlib data refresh lock."""
    return _release_lock(lock_key=lock_key, owner_token=owner_token)
