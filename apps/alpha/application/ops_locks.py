"""Shared lock helpers for Alpha/Qlib operational actions."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from celery.result import AsyncResult
from django.core.cache import cache

ALPHA_REFRESH_LOCK_TTL_SECONDS = 600
QLIB_REFRESH_LOCK_TTL_SECONDS = 1800

_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY = "alpha:ops:dashboard_refresh_lock_registry"
_INFERENCE_BATCH_REGISTRY_KEY = "alpha:ops:inference_batch_lock_registry"
_QLIB_DATA_REFRESH_REGISTRY_KEY = "alpha:ops:qlib_data_refresh_lock_registry"


def _lock_meta_key(lock_key: str) -> str:
    return f"{lock_key}:meta"


def _stable_fragment(value: str) -> str:
    digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return digest[:16]


def _register_lock(registry_key: str, lock_key: str) -> None:
    registry = list(cache.get(registry_key) or [])
    if lock_key not in registry:
        registry.append(lock_key)
        cache.set(registry_key, registry, timeout=None)


def _unregister_lock(registry_key: str, lock_key: str) -> None:
    registry = [item for item in list(cache.get(registry_key) or []) if item != lock_key]
    if registry:
        cache.set(registry_key, registry, timeout=None)
    else:
        cache.delete(registry_key)


def _store_lock_meta(
    *,
    registry_key: str,
    lock_key: str,
    meta: dict[str, Any],
    timeout: int,
) -> None:
    cache.set(_lock_meta_key(lock_key), meta, timeout=timeout)
    _register_lock(registry_key, lock_key)


def _clear_lock(registry_key: str, lock_key: str) -> None:
    cache.delete(lock_key)
    cache.delete(_lock_meta_key(lock_key))
    _unregister_lock(registry_key, lock_key)


def build_dashboard_alpha_refresh_lock_key(
    *,
    alpha_scope: str,
    target_date: date,
    top_n: int,
    raw_universe_id: str,
    resolved_pool=None,
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
    registry_key: str,
    lock_key: str,
    async_result_cls=AsyncResult,
) -> dict[str, Any] | None:
    existing_lock = cache.get(lock_key)
    if not existing_lock:
        _clear_lock(registry_key, lock_key)
        return None

    meta = dict(cache.get(_lock_meta_key(lock_key)) or {})
    if existing_lock == "__sync__":
        return {
            **meta,
            "status": "running",
            "mode": "sync",
            "task_id": None,
            "task_state": "RUNNING",
        }
    if existing_lock == "__pending__":
        return {
            **meta,
            "status": "running",
            "mode": "async",
            "task_id": None,
            "task_state": "PENDING",
        }

    task_id = str(existing_lock)
    try:
        task_result = async_result_cls(task_id)
        if task_result.ready():
            _clear_lock(registry_key, lock_key)
            return None
        task_state = getattr(task_result, "state", "PENDING")
    except Exception:
        task_state = "UNKNOWN"

    return {
        **meta,
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
) -> bool:
    acquired = cache.add(lock_key, "__pending__", timeout=timeout)
    if acquired:
        _store_lock_meta(registry_key=registry_key, lock_key=lock_key, meta=meta, timeout=timeout)
    return acquired


def _promote_async_lock(
    *,
    registry_key: str,
    lock_key: str,
    task_id: str,
    timeout: int,
    meta_updates: dict[str, Any] | None = None,
) -> None:
    cache.set(lock_key, task_id, timeout=timeout)
    meta = dict(cache.get(_lock_meta_key(lock_key)) or {})
    if meta_updates:
        meta.update(meta_updates)
    _store_lock_meta(registry_key=registry_key, lock_key=lock_key, meta=meta, timeout=timeout)


def _list_active_locks(
    *,
    registry_key: str,
    async_result_cls=AsyncResult,
) -> list[dict[str, Any]]:
    active_items: list[dict[str, Any]] = []
    for lock_key in list(cache.get(registry_key) or []):
        lock_meta = _resolve_async_lock(
            registry_key=registry_key,
            lock_key=lock_key,
            async_result_cls=async_result_cls,
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
    async_result_cls=AsyncResult,
) -> dict[str, Any] | None:
    """Return dashboard alpha refresh lock metadata, clearing stale locks."""
    return _resolve_async_lock(
        registry_key=_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_dashboard_alpha_refresh_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
) -> bool:
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
    task_id: str,
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> None:
    """Replace a pending dashboard alpha refresh lock with the Celery task id."""
    _promote_async_lock(
        registry_key=_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_dashboard_alpha_refresh_lock(lock_key: str) -> None:
    """Release a dashboard alpha refresh lock and its metadata."""
    _clear_lock(_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY, lock_key)


def list_active_dashboard_alpha_refresh_locks(async_result_cls=AsyncResult) -> list[dict[str, Any]]:
    """Return current dashboard alpha refresh locks visible to the ops page."""
    return _list_active_locks(
        registry_key=_DASHBOARD_ALPHA_REFRESH_REGISTRY_KEY,
        async_result_cls=async_result_cls,
    )


def resolve_inference_batch_lock(lock_key: str, *, async_result_cls=AsyncResult) -> dict[str, Any] | None:
    """Resolve one alpha inference batch lock."""
    return _resolve_async_lock(
        registry_key=_INFERENCE_BATCH_REGISTRY_KEY,
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_inference_batch_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
) -> bool:
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
    task_id: str,
    timeout: int = ALPHA_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> None:
    """Replace a pending alpha inference batch lock with the Celery task id."""
    _promote_async_lock(
        registry_key=_INFERENCE_BATCH_REGISTRY_KEY,
        lock_key=lock_key,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_inference_batch_lock(lock_key: str) -> None:
    """Release an alpha inference batch lock."""
    _clear_lock(_INFERENCE_BATCH_REGISTRY_KEY, lock_key)


def resolve_qlib_data_refresh_lock(lock_key: str, *, async_result_cls=AsyncResult) -> dict[str, Any] | None:
    """Resolve one qlib data refresh lock."""
    return _resolve_async_lock(
        registry_key=_QLIB_DATA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        async_result_cls=async_result_cls,
    )


def acquire_qlib_data_refresh_pending_lock(
    lock_key: str,
    *,
    meta: dict[str, Any],
    timeout: int = QLIB_REFRESH_LOCK_TTL_SECONDS,
) -> bool:
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
    task_id: str,
    timeout: int = QLIB_REFRESH_LOCK_TTL_SECONDS,
    meta_updates: dict[str, Any] | None = None,
) -> None:
    """Replace a pending qlib data refresh lock with the Celery task id."""
    _promote_async_lock(
        registry_key=_QLIB_DATA_REFRESH_REGISTRY_KEY,
        lock_key=lock_key,
        task_id=task_id,
        timeout=timeout,
        meta_updates=meta_updates,
    )


def release_qlib_data_refresh_lock(lock_key: str) -> None:
    """Release a qlib data refresh lock."""
    _clear_lock(_QLIB_DATA_REFRESH_REGISTRY_KEY, lock_key)
