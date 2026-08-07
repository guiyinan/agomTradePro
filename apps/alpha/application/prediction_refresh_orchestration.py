"""Inline Qlib data refresh orchestration for prediction tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from apps.alpha.domain.entities import AlphaPoolScope

RefreshUniverses = Callable[..., dict[str, Any]]
RefreshCodes = Callable[..., dict[str, Any]]
LatestDateLoader = Callable[[], date | None]
JsonSerializer = Callable[[Any], Any]


def refresh_runtime_for_prediction(
    *,
    trade_date: date,
    universe_id: str,
    pool_scope: AlphaPoolScope | None,
    latest_qlib_data_date: date | None,
    refresh_universes: RefreshUniverses,
    refresh_codes: RefreshCodes,
    get_latest_date: LatestDateLoader,
    make_json_safe: JsonSerializer,
) -> tuple[date | None, dict[str, Any]]:
    """Refresh stale Qlib data while preserving the task's injectable boundaries."""

    metadata: dict[str, Any] = {}
    if latest_qlib_data_date is not None:
        metadata["qlib_data_latest_date_before_refresh"] = latest_qlib_data_date.isoformat()
    if latest_qlib_data_date is not None and latest_qlib_data_date >= trade_date:
        metadata["qlib_runtime_refresh_status"] = "skipped"
        metadata["qlib_runtime_refresh_reason"] = "already_up_to_date"
        return latest_qlib_data_date, metadata

    try:
        if pool_scope is not None and getattr(pool_scope, "instrument_codes", None):
            refresh_summary = refresh_codes(
                target_date=trade_date,
                stock_codes=list(getattr(pool_scope, "instrument_codes", ()) or ()),
                universe_id=getattr(pool_scope, "universe_id", None) or universe_id,
                lookback_days=120,
            )
        else:
            refresh_summary = refresh_universes(
                target_date=trade_date,
                universes=[universe_id],
                lookback_days=400,
            )
    except Exception as exc:
        metadata["qlib_runtime_refresh_status"] = "failed"
        metadata["qlib_runtime_refresh_error"] = str(exc)
        return latest_qlib_data_date, metadata

    metadata["qlib_runtime_refresh_status"] = str(refresh_summary.get("status") or "unknown")
    metadata["qlib_runtime_refresh_summary"] = make_json_safe(refresh_summary)
    try:
        latest_after_refresh = get_latest_date()
    except Exception as exc:
        metadata["qlib_runtime_refresh_post_check_error"] = str(exc)
        return latest_qlib_data_date, metadata

    if latest_after_refresh is not None:
        metadata["qlib_data_latest_date_after_refresh"] = latest_after_refresh.isoformat()
    return latest_after_refresh, metadata


__all__ = ["refresh_runtime_for_prediction"]
