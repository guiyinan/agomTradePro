"""Refresh complete market facts before publishing the frozen market scope."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

from apps.data_center.domain.model_market_data import (
    ModelHistoryPreparationPort,
    ModelMarketDataPort,
)
from core.exceptions import DataFetchError


def refresh_market_price_inputs(
    port: ModelMarketDataPort, asset_codes: list[str], target_date: date
) -> tuple[str, ...]:
    """Refresh raw price facts and verify every current member before publication."""
    start_date = target_date - timedelta(days=120)
    if isinstance(port, ModelHistoryPreparationPort):
        port.prepare_stock_history(tuple(asset_codes), start_date, target_date)
    suspended: list[str] = []
    for code in asset_codes:
        try:
            rows = port.stock_history(code, start_date, target_date)
            if not rows or max(row.trade_date for row in rows) != target_date:
                raise DataFetchError(
                    "Current price observations missing", code="MODEL_MARKET_STALE"
                )
        except DataFetchError as exc:
            if (
                exc.code != "MODEL_MARKET_SUSPENDED"
                or exc.details.get("asset_code") != code
                or exc.details.get("suspended_through") != target_date.isoformat()
            ):
                raise
            suspended.append(code)
    return tuple(suspended)


@dataclass(frozen=True)
class MarketPublicationRefreshPorts:
    """Factories inject audited fact-only sync and the atomic publication coordinator."""

    list_codes: Callable[[], list[str]]
    sync_quotes: Callable[[list[str]], int]
    sync_valuations: Callable[[list[str], date], int]
    publish: Callable[[list[str]], int]


def refresh_market_publications(
    *, ports: MarketPublicationRefreshPorts, as_of_date: date, batch_size: int = 100
) -> dict[str, object]:
    """Publish only after every fact batch succeeds; counts measure sync operations."""
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 200
    ):
        raise ValueError("batch_size must be an integer from 1 to 200")
    if not isinstance(as_of_date, date):
        raise ValueError("as_of_date must be a date")
    codes = sorted(set(ports.list_codes()))
    requested = ((len(codes) + batch_size - 1) // batch_size) * 2 + 1 if codes else 0
    succeeded = failed = stored = 0
    errors: list[str] = []
    for offset in range(0, len(codes), batch_size):
        batch = codes[offset : offset + batch_size]
        operations: tuple[Callable[[], int], ...] = (
            partial(ports.sync_quotes, batch),
            partial(ports.sync_valuations, batch, as_of_date),
        )
        for operation in operations:
            try:
                count = operation()
                stored += count
                if count != len(batch):
                    raise DataFetchError("Market batch incomplete", code="MARKET_BATCH_INCOMPLETE")
                succeeded += 1
            except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
                failed += 1
                errors.append(getattr(exc, "code", type(exc).__name__))
    published = 0
    if codes and failed == 0:
        try:
            published = ports.publish(codes)
            if published <= 0:
                raise ValueError("Market publication produced no members")
            succeeded += 1
        except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
            failed += 1
            errors.append(getattr(exc, "code", type(exc).__name__))
    elif codes:
        failed += 1
        errors.append("market_publication_skipped_incomplete_refresh")
    outcome = "success" if published else "partial" if stored else "failed"
    return {
        "outcome": outcome,
        "success": outcome == "success",
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        "count_unit": "sync_operation",
        "asset_count": len(codes),
        "published_members": published,
        "publication_updated": bool(published),
        "errors": errors or ([] if codes else ["market_scope_empty"]),
    }
