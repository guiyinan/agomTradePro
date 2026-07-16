"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.core.cache import cache  # type: ignore[import-untyped]

from shared.infrastructure.operational_alert_registry import record_operational_alert

from .interface_services import (
    make_calculate_market_thermometer_use_case,
    make_sync_market_thermometer_inputs_use_case,
    refresh_decision_quote_snapshots,
)
from .market_thermometer_dates import resolve_market_thermometer_as_of_date

logger = logging.getLogger(__name__)

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"


def _resolve_market_thermometer_as_of_date(raw_as_of_date: str = "") -> Any:
    """Backward-compatible wrapper for existing tests and call sites."""

    return resolve_market_thermometer_as_of_date(raw_as_of_date)


@shared_task(
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
        "as_of_date": target_date.isoformat(),
        "sync": sync_payload,
        "snapshot": payload,
    }


@shared_task(
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
    return payload
