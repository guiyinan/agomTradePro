"""Task-wide fail-fast lease for full-market publication refreshes."""

from django.core.cache.backends.base import BaseCache, InvalidCacheBackendError
from redis.exceptions import RedisError

FULL_MARKET_REFRESH_LOCK_KEY = "data_center:full_market_publication_refresh:lock:v1"
FULL_MARKET_REFRESH_SOFT_TIME_LIMIT_SECONDS = 5400
FULL_MARKET_REFRESH_HARD_TIME_LIMIT_SECONDS = 5700
FULL_MARKET_REFRESH_AUTHORITY_WINDOW_SECONDS = 6300
FULL_MARKET_REFRESH_FINALIZATION_MARGIN_SECONDS = 300
FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS = (
    FULL_MARKET_REFRESH_HARD_TIME_LIMIT_SECONDS + FULL_MARKET_REFRESH_FINALIZATION_MARGIN_SECONDS
)


class FullMarketRefreshLeaseUnavailable(RuntimeError):
    """Indicate that the fail-closed task lease cache could not be used."""

    def __init__(self, operation: str) -> None:
        super().__init__("full-market refresh lease cache is unavailable")
        self.operation = operation


def claim_full_market_refresh_lease(cache_backend: BaseCache, owner_id: str) -> bool:
    """Atomically claim the bounded lease for one full-market task invocation."""

    try:
        acquired = cache_backend.add(
            FULL_MARKET_REFRESH_LOCK_KEY,
            owner_id,
            timeout=FULL_MARKET_REFRESH_LOCK_LEASE_TTL_SECONDS,
        )
    except (InvalidCacheBackendError, OSError, RedisError) as exc:
        raise FullMarketRefreshLeaseUnavailable("claim") from exc
    if type(acquired) is not bool:
        raise FullMarketRefreshLeaseUnavailable("claim")
    return acquired


def release_full_market_refresh_lease(cache_backend: BaseCache, owner_id: str) -> bool:
    """Delete the lease only when its current owner matches this invocation."""

    try:
        current_owner: object = cache_backend.get(FULL_MARKET_REFRESH_LOCK_KEY)
        if current_owner != owner_id:
            return False
        deleted = cache_backend.delete(FULL_MARKET_REFRESH_LOCK_KEY)
    except (InvalidCacheBackendError, OSError, RedisError) as exc:
        raise FullMarketRefreshLeaseUnavailable("release") from exc
    if type(deleted) is not bool:
        raise FullMarketRefreshLeaseUnavailable("release")
    return deleted


def full_market_refresh_lease_busy_result() -> dict[str, object]:
    """Return the stable no-op result when another full-market run owns the lease."""

    return {
        "outcome": "noop",
        "success": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "stage": "lease",
        "phase": "lease",
        "published_members": 0,
        "must_not_use_for_decision": True,
        "error_code": "FULL_MARKET_REFRESH_ALREADY_RUNNING",
        "noop_reason": "full_market_refresh_already_running",
        "publication_updated": False,
    }


def full_market_refresh_lease_unavailable_result() -> dict[str, object]:
    """Return the stable zero-write block when the lease cache is unavailable."""

    return {
        "outcome": "blocked",
        "success": False,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "stage": "lease",
        "phase": "lease",
        "published_members": 0,
        "must_not_use_for_decision": True,
        "error_code": "FULL_MARKET_REFRESH_LEASE_UNAVAILABLE",
        "blocked_reason": "full_market_refresh_lease_unavailable",
        "publication_updated": False,
    }
