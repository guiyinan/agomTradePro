"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from celery import shared_task
from django.utils import timezone

from .interface_services import (
    make_calculate_market_thermometer_use_case,
    make_sync_market_thermometer_inputs_use_case,
)

logger = logging.getLogger(__name__)

MARKET_THERMOMETER_POST_CLOSE_HOUR = 16
MARKET_THERMOMETER_POST_CLOSE_MINUTE = 0


def _previous_business_day(target_date: date) -> date:
    """Return the latest weekday before ``target_date``."""

    previous_day = target_date - timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= timedelta(days=1)
    return previous_day


def _resolve_market_thermometer_as_of_date(raw_as_of_date: str = "") -> date:
    """Resolve the trade date that should be refreshed for one task run."""

    normalized = str(raw_as_of_date or "").strip()
    if normalized:
        return date.fromisoformat(normalized)

    local_now = timezone.localtime()
    current_date = local_now.date()
    if current_date.weekday() >= 5:
        return _previous_business_day(current_date)
    if (local_now.hour, local_now.minute) < (
        MARKET_THERMOMETER_POST_CLOSE_HOUR,
        MARKET_THERMOMETER_POST_CLOSE_MINUTE,
    ):
        return _previous_business_day(current_date)
    return current_date


@shared_task(
    name="apps.data_center.application.tasks.refresh_market_thermometer_task",
    time_limit=1800,
    soft_time_limit=1700,
)
def refresh_market_thermometer_task(as_of_date: str = "") -> dict[str, Any]:
    """Sync thermometer inputs and persist one fresh snapshot."""

    target_date = _resolve_market_thermometer_as_of_date(as_of_date)
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
