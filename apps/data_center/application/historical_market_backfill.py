"""Shared contracts for explicit-date historical market-fact backfills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime

from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptState,
)
from apps.data_center.domain.target_date_universe import TargetDateAssetUniverseScope


def require_historical_universe_evidence(
    target_trade_date: date,
    loader: Callable[[], Mapping[str, object]] | None,
) -> Mapping[str, object]:
    """Load exact target-date universe evidence or fail before provider writes."""

    if isinstance(target_trade_date, datetime):
        raise ValueError("historical market date must not contain a time")
    if loader is None:
        raise ValueError("historical market backfill requires target-date universe evidence")
    evidence = loader()
    if evidence.get("target_trade_date") != target_trade_date.isoformat():
        raise ValueError("target-date universe evidence does not match the historical date")
    return evidence


def build_partial_terminal_attempts(
    attempts: Sequence[SyncItemAttempt],
    *,
    succeeded_asset_codes: set[str],
    missing_error_code: str,
    finished_at: datetime,
) -> list[SyncItemAttempt]:
    """Build per-asset terminal evidence for an incomplete historical batch."""

    return [
        attempt.finish(
            state=(
                SyncItemAttemptState.SUCCEEDED
                if attempt.asset_code in succeeded_asset_codes
                else SyncItemAttemptState.FAILED
            ),
            finished_at=finished_at,
            stored_count=1 if attempt.asset_code in succeeded_asset_codes else 0,
            error_code="" if attempt.asset_code in succeeded_asset_codes else missing_error_code,
        )
        for attempt in attempts
    ]


def target_date_universe_evidence(
    scope: TargetDateAssetUniverseScope,
) -> dict[str, object]:
    """Return bounded count/hash evidence for one target-date A-share scope."""

    def scope_sha256(asset_codes: tuple[str, ...]) -> str:
        payload = json.dumps(list(asset_codes), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    return {
        "schema": "historical-market-universe.v1",
        "target_trade_date": scope.target_date.isoformat(),
        "candidate_count": len(scope.candidate_codes),
        "candidate_sha256": scope_sha256(scope.candidate_codes),
        "requested_count": len(scope.requested_codes),
        "requested_sha256": scope_sha256(scope.requested_codes),
        "excluded_not_yet_listed_count": len(scope.excluded_not_yet_listed),
        "unknown_listing_date_count": len(scope.unknown_listing_date_codes),
    }
