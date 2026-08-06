"""Celery tasks for realtime price polling."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

from celery import shared_task

from apps.realtime.domain.entities import PricePollingConfig, normalize_asset_code
from shared.domain.task_outcomes import TaskBusinessOutcome

logger = logging.getLogger(__name__)

_TASK_SOURCE = "realtime_price_polling"
_INCOMPLETE_REASON = "realtime_price_snapshot_incomplete"
_MISSING_REASON = "realtime_price_snapshot_missing"
_STALE_REASON = "realtime_price_snapshot_stale"
_NO_ASSETS_REASON = "no_monitored_realtime_assets"


def _normalize_asset_codes(asset_codes: object) -> list[str] | None:
    """Validate and canonicalize optional asset codes at the Celery boundary."""

    if asset_codes is None:
        return None
    if not isinstance(asset_codes, list):
        raise ValueError("asset_codes must be a list of strings or null")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_code in asset_codes:
        if not isinstance(raw_code, str):
            raise ValueError("asset_codes must contain only strings")
        if not raw_code.strip():
            continue
        code = normalize_asset_code(raw_code)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    return normalized


def _parse_aware_timestamp(value: object) -> datetime | None:
    """Parse one serialized source timestamp without substituting the task clock."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _fresh_price_payloads(
    raw_prices: object,
    *,
    requested_codes: set[str] | None,
    reference_time: datetime,
) -> tuple[list[dict[str, object]], int]:
    """Return unique fresh quotes and the count rejected for stale/invalid clocks."""

    if not isinstance(raw_prices, list):
        return [], 0

    maximum_age = timedelta(seconds=PricePollingConfig().max_price_age_seconds)
    fresh: list[dict[str, object]] = []
    seen: set[str] = set()
    stale_or_invalid = 0
    for raw_price in raw_prices:
        if not isinstance(raw_price, Mapping):
            stale_or_invalid += 1
            continue
        try:
            asset_code = normalize_asset_code(str(raw_price.get("asset_code") or ""))
        except ValueError:
            stale_or_invalid += 1
            continue
        if asset_code in seen or (
            requested_codes is not None and asset_code not in requested_codes
        ):
            continue
        observed_at = _parse_aware_timestamp(raw_price.get("timestamp"))
        if observed_at is None:
            stale_or_invalid += 1
            continue
        age = reference_time - observed_at
        if age < timedelta(0) or age > maximum_age:
            stale_or_invalid += 1
            continue
        payload = {
            str(key): cast(object, value)
            for key, value in raw_price.items()
            if isinstance(key, str)
        }
        payload["asset_code"] = asset_code
        payload["timestamp"] = observed_at.isoformat()
        fresh.append(payload)
        seen.add(asset_code)
    return fresh, stale_or_invalid


def _freshness_metadata(
    *,
    prices: list[dict[str, object]],
    outcome: TaskBusinessOutcome,
    stale_or_invalid: int,
    blocked_reason: str,
    technical_failure: bool,
) -> dict[str, object]:
    """Publish aggregate source-time evidence without washing observation clocks."""

    observed_times = [
        timestamp
        for price in prices
        if (timestamp := _parse_aware_timestamp(price.get("timestamp"))) is not None
    ]
    fetched_times = [
        timestamp
        for price in prices
        if (timestamp := _parse_aware_timestamp(price.get("fetched_at"))) is not None
    ]
    sources = sorted(
        {source for price in prices if (source := str(price.get("source") or "").strip())}
    )
    is_fresh = outcome is TaskBusinessOutcome.SUCCESS
    if is_fresh:
        reliability_status = "fresh"
    elif outcome is TaskBusinessOutcome.PARTIAL:
        reliability_status = "partial"
    elif technical_failure:
        reliability_status = "failed"
    elif stale_or_invalid:
        reliability_status = "stale"
    elif outcome is TaskBusinessOutcome.BLOCKED:
        reliability_status = "failed"
    else:
        reliability_status = "missing"
    return {
        "observed_at": min(observed_times).isoformat() if observed_times else None,
        "latest_observed_at": max(observed_times).isoformat() if observed_times else None,
        "fetched_at": max(fetched_times).isoformat() if fetched_times else None,
        "source": sources[0] if len(sources) == 1 else (_TASK_SOURCE if not sources else "mixed"),
        "sources": sources,
        "freshness_status": reliability_status,
        "reliability_status": reliability_status,
        "is_reliable": is_fresh,
        "is_stale": reliability_status == "stale",
        "must_not_use_for_decision": not is_fresh,
        "blocked_reason": "" if is_fresh else blocked_reason,
        "stale_or_invalid": stale_or_invalid,
    }


def _task_result(
    *,
    outcome: TaskBusinessOutcome,
    mode: str,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
    prices: list[dict[str, object]],
    asset_codes: list[str],
    stale_or_invalid: int = 0,
    blocked_reason: str = "",
    error: str = "",
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one normalized polling result for every task exit path."""

    result = dict(extra or {})
    result.update(
        {
            "success": outcome
            in {
                TaskBusinessOutcome.SUCCESS,
                TaskBusinessOutcome.PARTIAL,
                TaskBusinessOutcome.NOOP,
            },
            "outcome": outcome.value,
            "mode": mode,
            "requested": requested,
            "succeeded": succeeded,
            "failed": failed,
            "stored": stored,
            "asset_codes": asset_codes,
            "prices": prices,
            "error": error,
        }
    )
    result.update(
        _freshness_metadata(
            prices=prices,
            outcome=outcome,
            stale_or_invalid=stale_or_invalid,
            blocked_reason=blocked_reason,
            technical_failure=bool(error),
        )
    )
    return result


@shared_task(  # type: ignore[misc]
    name="apps.realtime.application.tasks.poll_realtime_prices_task",
    time_limit=600,
    soft_time_limit=570,
)
def poll_realtime_prices_task(
    asset_codes: list[str] | None = None,
) -> dict[str, object]:
    """Poll the watchlist or query a subset with normalized freshness evidence."""

    try:
        requested_codes = _normalize_asset_codes(asset_codes)
    except ValueError as exc:
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            mode="input",
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            prices=[],
            asset_codes=[],
            blocked_reason=_MISSING_REASON,
            error=str(exc),
        )

    from apps.realtime.application.price_polling_service import PricePollingUseCase

    mode = "requested_assets" if requested_codes else "watchlist"
    requested_count = len(requested_codes or [])
    try:
        use_case = PricePollingUseCase()
        if requested_codes:
            logger.info(
                "Polling realtime prices for %s requested assets",
                requested_count,
            )
            raw_prices = use_case.get_latest_prices(requested_codes)
            reference_time = datetime.now(UTC)
            prices, rejected = _fresh_price_payloads(
                raw_prices,
                requested_codes=set(requested_codes),
                reference_time=reference_time,
            )
            succeeded = len(prices)
            failed = requested_count - succeeded
            if succeeded == 0:
                outcome = TaskBusinessOutcome.FAILED
            elif failed:
                outcome = TaskBusinessOutcome.PARTIAL
            else:
                outcome = TaskBusinessOutcome.SUCCESS
            blocked_reason = (
                ""
                if outcome is TaskBusinessOutcome.SUCCESS
                else (_STALE_REASON if rejected and succeeded == 0 else _INCOMPLETE_REASON)
            )
            return _task_result(
                outcome=outcome,
                mode=mode,
                requested=requested_count,
                succeeded=succeeded,
                failed=failed,
                stored=0,
                prices=prices,
                asset_codes=requested_codes,
                stale_or_invalid=rejected,
                blocked_reason=blocked_reason,
            )

        logger.info("Polling realtime prices for the monitored watchlist")
        raw_snapshot = use_case.execute_price_polling()
        if not isinstance(raw_snapshot, Mapping):
            raise TypeError("price polling use case returned an invalid snapshot")
        raw_total = raw_snapshot.get("total_assets", 0)
        if isinstance(raw_total, bool) or not isinstance(raw_total, int) or raw_total < 0:
            raise ValueError("price polling snapshot total_assets is invalid")
        requested_count = raw_total
        reference_time = datetime.now(UTC)
        prices, rejected = _fresh_price_payloads(
            raw_snapshot.get("prices"),
            requested_codes=None,
            reference_time=reference_time,
        )
        if len(prices) > requested_count:
            prices = prices[:requested_count]
        succeeded = len(prices)
        failed = requested_count - succeeded
        upstream_blocked = bool(raw_snapshot.get("must_not_use_for_decision"))
        if requested_count == 0:
            outcome = TaskBusinessOutcome.NOOP
            blocked_reason = _NO_ASSETS_REASON
        elif succeeded == 0:
            outcome = TaskBusinessOutcome.FAILED
            blocked_reason = _STALE_REASON if rejected else _MISSING_REASON
        elif failed:
            outcome = TaskBusinessOutcome.PARTIAL
            blocked_reason = _INCOMPLETE_REASON
        elif upstream_blocked:
            outcome = TaskBusinessOutcome.BLOCKED
            blocked_reason = str(raw_snapshot.get("blocked_reason") or _INCOMPLETE_REASON)
        else:
            outcome = TaskBusinessOutcome.SUCCESS
            blocked_reason = ""
        snapshot_extra = {
            str(key): cast(object, value)
            for key, value in raw_snapshot.items()
            if isinstance(key, str) and key not in {"prices", "success", "outcome"}
        }
        return _task_result(
            outcome=outcome,
            mode=mode,
            requested=requested_count,
            succeeded=succeeded,
            failed=failed,
            stored=succeeded,
            prices=prices,
            asset_codes=[],
            stale_or_invalid=rejected,
            blocked_reason=blocked_reason,
            extra=snapshot_extra,
        )
    except Exception:
        logger.exception("Realtime price polling task failed mode=%s", mode)
        return _task_result(
            outcome=TaskBusinessOutcome.FAILED,
            mode=mode,
            requested=requested_count,
            succeeded=0,
            failed=requested_count,
            stored=0,
            prices=[],
            asset_codes=requested_codes or [],
            blocked_reason=_MISSING_REASON,
            error="realtime_price_polling_failed",
        )
