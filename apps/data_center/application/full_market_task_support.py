"""Pure validation and outcome helpers for the full-market Celery task."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from shared.domain.task_outcomes import TaskBusinessOutcome


def data02_authority_failure(reason: str) -> dict[str, object]:
    """Return a stable zero-write authority denial for DATA-02 tasks."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "authority",
        "blocked_reason": reason,
        "must_not_use_for_decision": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "checkpoint": {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        },
    }


def exact_provider_batch_count(
    *,
    requested_asset_codes: Sequence[str],
    stored_count: object,
    returned_asset_codes: object,
    succeeded_asset_codes: object | None = None,
) -> int:
    """Return the stored count only when every requested identity is exact."""

    if isinstance(stored_count, bool) or not isinstance(stored_count, int):
        raise ValueError("provider batch stored_count must be an integer")
    if isinstance(returned_asset_codes, (str, bytes)) or not isinstance(
        returned_asset_codes, Sequence
    ):
        raise ValueError("provider batch asset identities are unavailable")
    requested = tuple(str(code or "").strip().upper() for code in requested_asset_codes)
    returned = tuple(str(code or "").strip().upper() for code in returned_asset_codes)
    succeeded = returned
    if succeeded_asset_codes is not None:
        if isinstance(succeeded_asset_codes, (str, bytes)) or not isinstance(
            succeeded_asset_codes, Sequence
        ):
            raise ValueError("provider batch succeeded identities are unavailable")
        succeeded = tuple(str(code or "").strip().upper() for code in succeeded_asset_codes)
    if (
        any(not code for code in (*requested, *returned, *succeeded))
        or len(set(requested)) != len(requested)
        or len(set(returned)) != len(returned)
        or len(set(succeeded)) != len(succeeded)
        or stored_count != len(requested)
        or len(returned) != len(requested)
        or len(succeeded) != len(requested)
        or set(returned) != set(requested)
        or set(succeeded) != set(requested)
    ):
        raise ValueError("provider batch asset identities are incomplete")
    return stored_count


def full_market_input_failure(reason: str) -> dict[str, object]:
    """Publish a stable zero-write failure before any market fetch."""

    return {
        "outcome": "failed",
        "success": False,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "blocked_reason": reason,
    }


def full_market_soft_timeout_failure(
    *,
    requested_operations: int,
    completed_operations: int,
    stored_rows: int,
    target_trade_date: str,
    phase: str,
    asset_count: int,
    publication_run_id: str,
    quote_source: str,
    valuation_source: str,
    market_universe: Mapping[str, object],
    valuation_seed_stored: int,
    excluded_non_trading_codes: Sequence[str],
) -> dict[str, object]:
    """Return a durable business result when the worker reaches its soft deadline."""

    excluded = tuple(excluded_non_trading_codes)
    return {
        "outcome": TaskBusinessOutcome.FAILED.value,
        "success": False,
        "requested": requested_operations,
        "succeeded": completed_operations,
        "failed": 1,
        "stored": stored_rows,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "target_trade_date": target_trade_date,
        "phase": phase,
        "asset_count": asset_count,
        "published_members": 0,
        "publication_updated": False,
        "publication_run_id": publication_run_id,
        "error_code": "MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED",
        "blocked_reason": "market_refresh_soft_time_limit_exceeded",
        "errors": ["MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED"],
        "must_not_use_for_decision": True,
        "quote_source": quote_source,
        "valuation_source": valuation_source,
        "market_universe": dict(market_universe),
        "valuation_seed_stored": valuation_seed_stored,
        "excluded_non_trading_count": len(excluded),
        "excluded_non_trading_codes": list(excluded),
    }
