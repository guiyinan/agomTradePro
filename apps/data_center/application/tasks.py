"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

from .dtos import (
    SyncFinancialRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
)
from .interface_services import (
    get_active_provider_id_by_source,
    make_calculate_market_thermometer_use_case,
    make_sync_current_valuation_batch_use_case,
    make_sync_financial_use_case,
    make_sync_market_thermometer_inputs_use_case,
    make_sync_price_use_case,
    make_sync_quote_use_case,
    refresh_decision_quote_snapshots,
)
from .market_thermometer_dates import resolve_market_thermometer_as_of_date
from .query_services import list_active_stock_codes_for_backfill
from .query_use_cases import latest_completed_cn_market_session

logger = logging.getLogger(__name__)

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"


def _resolve_market_thermometer_as_of_date(raw_as_of_date: str = "") -> date:
    """Backward-compatible wrapper for existing tests and call sites."""

    return resolve_market_thermometer_as_of_date(raw_as_of_date)


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.refresh_market_thermometer_task",
    time_limit=1800,
    soft_time_limit=1700,
)
def refresh_market_thermometer_task(as_of_date: str = "") -> dict[str, Any]:
    """Sync thermometer inputs and persist one fresh snapshot."""

    target_date = resolve_market_thermometer_as_of_date(as_of_date)
    sync_payload = make_sync_market_thermometer_inputs_use_case().execute(as_of_date=target_date)
    snapshot = make_calculate_market_thermometer_use_case().execute(as_of_date=target_date)
    payload = snapshot.to_dict()
    logger.info(
        "Market thermometer refreshed for %s with score=%s valid_components=%s data_source=%s",
        target_date.isoformat(),
        payload["score"],
        payload["valid_component_count"],
        payload["data_source"],
    )
    return {
        "success": not bool(payload.get("must_not_use_for_decision")),
        "outcome": (
            TaskBusinessOutcome.BLOCKED.value
            if payload.get("must_not_use_for_decision")
            else TaskBusinessOutcome.SUCCESS.value
        ),
        "as_of_date": target_date.isoformat(),
        "sync": sync_payload,
        "snapshot": payload,
    }


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
    time_limit=900,
    soft_time_limit=840,
)
def refresh_decision_quote_snapshots_task(
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Refresh quote snapshots required by decision-grade outputs."""

    payload = refresh_decision_quote_snapshots(
        asset_codes=asset_codes,
        quote_max_age_hours=quote_max_age_hours,
    )
    logger.info(
        "Decision quote snapshots refreshed status=%s synced=%s blocked=%s",
        payload["status"],
        payload["synced_count"],
        payload["must_not_use_for_decision"],
    )
    readiness = payload.get("readiness") or {}
    thermometer = readiness.get("market_thermometer") or {}
    degraded = bool(
        payload.get("degraded")
        or thermometer.get("data_source") == "degraded"
        or readiness.get("data_source") == "degraded"
    )
    blocked = bool(payload.get("must_not_use_for_decision"))
    if degraded or blocked:
        streak = int(cache.get(DECISION_QUOTE_DEGRADED_STREAK_KEY, 0) or 0) + 1
        cache.set(DECISION_QUOTE_DEGRADED_STREAK_KEY, streak, timeout=7 * 86400)
        if blocked or streak == 3:
            record_operational_alert(
                level="critical" if blocked else "warning",
                task_name=(
                    "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task"
                ),
                title=(
                    "Decision quote data is blocked"
                    if blocked
                    else "Decision quote data degraded for three consecutive runs"
                ),
                message=(
                    "Decision-grade quote refresh requires operator review."
                    if blocked
                    else "Fallback data remained active for three consecutive refreshes."
                ),
                metadata={
                    "degraded_streak": streak,
                    "must_not_use_for_decision": blocked,
                    "asset_codes": payload.get("asset_codes") or asset_codes or [],
                },
            )
    else:
        cache.delete(DECISION_QUOTE_DEGRADED_STREAK_KEY)
    payload["degraded"] = degraded
    payload["success"] = not blocked
    payload["outcome"] = (
        TaskBusinessOutcome.BLOCKED.value
        if blocked
        else (TaskBusinessOutcome.PARTIAL.value if degraded else TaskBusinessOutcome.SUCCESS.value)
    )
    return payload


def _validated_backfill_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Validate a bounded integer at the Celery task boundary."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.backfill_active_a_share_core_data_batch_task",
    time_limit=3600,
    soft_time_limit=3500,
)
def backfill_active_a_share_core_data_batch_task(
    *,
    offset: int = 0,
    batch_size: int = 50,
    source: str = "tushare",
    history_days: int = 756,
    financial_periods: int = 8,
) -> dict[str, Any]:
    """Backfill one resumable active-A-share core-data batch."""

    try:
        validated_offset = _validated_backfill_int(
            offset,
            field_name="offset",
            minimum=0,
            maximum=100_000,
        )
        validated_batch_size = _validated_backfill_int(
            batch_size,
            field_name="batch_size",
            minimum=1,
            maximum=200,
        )
        validated_history_days = _validated_backfill_int(
            history_days,
            field_name="history_days",
            minimum=30,
            maximum=3660,
        )
        validated_periods = _validated_backfill_int(
            financial_periods,
            field_name="financial_periods",
            minimum=1,
            maximum=40,
        )
        normalized_source = str(source or "").strip().lower()
        if not normalized_source or len(normalized_source) > 32:
            raise ValueError("source must be a non-empty identifier")
    except ValueError as exc:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "input",
            "error": str(exc),
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
        }

    asset_codes = list_active_stock_codes_for_backfill()
    total_assets = len(asset_codes)
    batch_codes = asset_codes[validated_offset : validated_offset + validated_batch_size]
    next_offset = validated_offset + len(batch_codes)
    checkpoint = {
        "offset": validated_offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
    }
    if not batch_codes:
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.NOOP.value,
            "stage": "complete",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "noop_reason": "no remaining active A-share assets",
            "checkpoint": checkpoint,
        }

    provider_id = get_active_provider_id_by_source(normalized_source)
    if provider_id is None:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "provider",
            "error": f"no active provider for source: {normalized_source}",
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": len(batch_codes),
            "stored": 0,
            "checkpoint": {**checkpoint, "complete": False},
        }

    end_date = latest_completed_cn_market_session(timezone.now())
    if end_date is None:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "market_calendar",
            "error": "latest completed China market session is unavailable",
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": len(batch_codes),
            "stored": 0,
            "checkpoint": {**checkpoint, "complete": False},
        }
    start_date = end_date - timedelta(days=validated_history_days)
    quote_use_case = make_sync_quote_use_case()
    price_use_case = make_sync_price_use_case()
    valuation_batch_use_case = make_sync_current_valuation_batch_use_case()
    financial_use_case = make_sync_financial_use_case()

    domain_counts: dict[str, dict[str, int]] = {
        name: {"requested": len(batch_codes), "succeeded": 0, "failed": 0, "stored": 0}
        for name in ("quote", "price", "valuation", "financial")
    }
    errors: list[dict[str, str]] = []
    failed_asset_codes: set[str] = set()
    try:
        quote_result = quote_use_case.execute(
            SyncQuoteRequest(provider_id=provider_id, asset_codes=batch_codes)
        )
        quote_stored = int(quote_result.stored_count)
        domain_counts["quote"]["stored"] = quote_stored
        domain_counts["quote"]["succeeded"] = min(quote_stored, len(batch_codes))
        domain_counts["quote"]["failed"] = max(len(batch_codes) - quote_stored, 0)
    except Exception:
        domain_counts["quote"]["failed"] = len(batch_codes)
        errors.append({"domain": "quote", "asset_code": "batch", "error": "sync_failed"})

    try:
        valuation_result = valuation_batch_use_case.execute(
            provider_id=provider_id,
            asset_codes=batch_codes,
            as_of_date=end_date,
        )
        valuation_succeeded = set(valuation_result.succeeded_asset_codes)
        valuation_missing = set(batch_codes) - valuation_succeeded
        domain_counts["valuation"]["stored"] = int(valuation_result.stored_count)
        domain_counts["valuation"]["succeeded"] = len(valuation_succeeded)
        domain_counts["valuation"]["failed"] = len(valuation_missing)
        failed_asset_codes.update(valuation_missing)
        for asset_code in sorted(valuation_missing)[:20]:
            errors.append({"domain": "valuation", "asset_code": asset_code, "error": "zero_output"})
    except Exception:
        domain_counts["valuation"]["failed"] = len(batch_codes)
        failed_asset_codes.update(batch_codes)
        errors.append({"domain": "valuation", "asset_code": "batch", "error": "sync_failed"})

    for asset_code in batch_codes:
        domain_names = ("price", "financial")
        for domain_name in domain_names:
            try:
                result: SyncResult
                if domain_name == "price":
                    result = price_use_case.execute(
                        SyncPriceRequest(
                            provider_id=provider_id,
                            asset_code=asset_code,
                            start=start_date,
                            end=end_date,
                        )
                    )
                else:
                    result = financial_use_case.execute(
                        SyncFinancialRequest(
                            provider_id=provider_id,
                            asset_code=asset_code,
                            periods=validated_periods,
                        )
                    )
                stored_count = int(result.stored_count)
                domain_counts[domain_name]["stored"] += stored_count
                if stored_count > 0:
                    domain_counts[domain_name]["succeeded"] += 1
                else:
                    domain_counts[domain_name]["failed"] += 1
                    failed_asset_codes.add(asset_code)
                    if len(errors) < 20:
                        errors.append(
                            {
                                "domain": domain_name,
                                "asset_code": asset_code,
                                "error": "zero_output",
                            }
                        )
            except Exception:
                domain_counts[domain_name]["failed"] += 1
                failed_asset_codes.add(asset_code)
                if len(errors) < 20:
                    errors.append(
                        {
                            "domain": domain_name,
                            "asset_code": asset_code,
                            "error": "sync_failed",
                        }
                    )
    quote_missing = domain_counts["quote"]["failed"]
    failed_total = max(len(failed_asset_codes), quote_missing)
    succeeded_total = max(len(batch_codes) - failed_total, 0)
    stored_total = sum(item["stored"] for item in domain_counts.values())
    if failed_total == len(batch_codes):
        outcome = TaskBusinessOutcome.FAILED
    elif failed_total > 0:
        outcome = TaskBusinessOutcome.PARTIAL
    elif stored_total == 0:
        outcome = TaskBusinessOutcome.NOOP
    else:
        outcome = TaskBusinessOutcome.SUCCESS

    return {
        "success": outcome not in {TaskBusinessOutcome.FAILED, TaskBusinessOutcome.BLOCKED},
        "outcome": outcome.value,
        "stage": "batch",
        "source": normalized_source,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "asset_codes": batch_codes,
        "requested": len(batch_codes),
        "succeeded": succeeded_total,
        "failed": failed_total,
        "stored": stored_total,
        "domains": domain_counts,
        "errors": errors,
        "checkpoint": checkpoint,
    }
