"""Cache-backed lease and resumable checkpoint support for financial refreshes."""

from collections.abc import Mapping

from django.core.cache.backends.base import BaseCache

FINANCIAL_REFRESH_LOCK_KEY = "data_center:financial_publication_refresh:lock:v2"
FINANCIAL_REFRESH_PROGRESS_KEY = "data_center:financial_publication_refresh:progress:v1"
FINANCIAL_REFRESH_LOCK_LEASE_TTL = 3900
FINANCIAL_REFRESH_CHECKPOINT_TTL = 7 * 86400


def financial_refresh_lock_noop_result() -> dict[str, object]:
    """Return the stable task result used when another workflow holds the lease."""

    return {
        "success": True,
        "outcome": "noop",
        "stage": "lock",
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "noop_reason": "financial_refresh_already_running",
    }


def release_financial_refresh_lock(cache_backend: BaseCache, workflow_id: str) -> None:
    """Release a financial refresh lease only while the caller still owns it."""

    current_owner: object = cache_backend.get(FINANCIAL_REFRESH_LOCK_KEY)
    if current_owner == workflow_id:
        cache_backend.delete(FINANCIAL_REFRESH_LOCK_KEY)


def claim_financial_refresh_lock(cache_backend: BaseCache, workflow_id: str) -> bool:
    """Acquire or renew the short lease for one financial refresh workflow."""

    current_owner: object = cache_backend.get(FINANCIAL_REFRESH_LOCK_KEY)
    if current_owner == workflow_id:
        lease_renewed = cache_backend.touch(
            FINANCIAL_REFRESH_LOCK_KEY,
            timeout=FINANCIAL_REFRESH_LOCK_LEASE_TTL,
        )
        if not lease_renewed:
            return False
        renewed_owner: object = cache_backend.get(FINANCIAL_REFRESH_LOCK_KEY)
        return isinstance(renewed_owner, str) and renewed_owner == workflow_id
    if current_owner is None:
        return cache_backend.add(
            FINANCIAL_REFRESH_LOCK_KEY,
            workflow_id,
            timeout=FINANCIAL_REFRESH_LOCK_LEASE_TTL,
        )
    return False


def restore_financial_refresh_offset(
    cache_backend: BaseCache,
    *,
    universe_hash: str,
    source: str,
    financial_periods: int,
    batch_size: int,
    total_assets: int,
) -> int | None:
    """Return a compatible checkpoint offset, or None when it cannot be resumed."""

    progress_value: object = cache_backend.get(FINANCIAL_REFRESH_PROGRESS_KEY)
    if not isinstance(progress_value, Mapping):
        return None
    next_offset: object = progress_value.get("next_offset")
    if (
        progress_value.get("universe_hash") != universe_hash
        or progress_value.get("source") != source
        or progress_value.get("financial_periods") != financial_periods
        or progress_value.get("batch_size") != batch_size
        or isinstance(next_offset, bool)
        or not isinstance(next_offset, int)
        or not 0 <= next_offset <= total_assets
    ):
        return None
    return next_offset


def save_financial_refresh_progress(
    cache_backend: BaseCache,
    *,
    next_offset: int,
    universe_hash: str,
    source: str,
    financial_periods: int,
    batch_size: int,
) -> None:
    """Persist a resumable checkpoint independently of the short lock lease."""

    progress_payload: dict[str, object] = {
        "next_offset": next_offset,
        "universe_hash": universe_hash,
        "source": source,
        "financial_periods": financial_periods,
        "batch_size": batch_size,
    }
    cache_backend.set(
        FINANCIAL_REFRESH_PROGRESS_KEY,
        progress_payload,
        timeout=FINANCIAL_REFRESH_CHECKPOINT_TTL,
    )


def clear_financial_refresh_progress(cache_backend: BaseCache) -> None:
    """Remove the saved financial refresh checkpoint."""

    cache_backend.delete(FINANCIAL_REFRESH_PROGRESS_KEY)


def financial_refresh_checkpoint(
    *,
    offset: int,
    next_offset: int,
    total_assets: int,
    universe_hash: str,
) -> dict[str, object]:
    """Build the stable visible checkpoint for one financial refresh batch."""

    return {
        "offset": offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
        "universe_hash": universe_hash,
    }
