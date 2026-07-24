"""Fail-safe forwarding of broker-execution alerts to task monitoring."""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

_REQUIRED_TEXT_FIELDS = ("level", "task_name", "title", "message")


def forward_operational_alerts(alerts: object) -> tuple[list[str], int]:
    """Forward valid alerts without letting monitoring failures retry business writes."""

    if alerts is None:
        return [], 0
    if not isinstance(alerts, list):
        logger.error("Broker execution returned a non-list alerts payload")
        return [], 1

    alert_ids: list[str] = []
    failure_count = 0
    for raw_alert in alerts:
        if not isinstance(raw_alert, Mapping):
            failure_count += 1
            logger.error("Broker execution returned a non-mapping alert")
            continue

        text_fields: dict[str, str] = {}
        malformed = False
        for field_name in _REQUIRED_TEXT_FIELDS:
            value = raw_alert.get(field_name)
            if not isinstance(value, str) or not value.strip():
                malformed = True
                break
            text_fields[field_name] = value.strip()
        metadata = raw_alert.get("metadata")
        task_id = raw_alert.get("task_id", "")
        if (
            malformed
            or (metadata is not None and not isinstance(metadata, Mapping))
            or not isinstance(task_id, str)
        ):
            failure_count += 1
            logger.error("Broker execution returned a malformed alert")
            continue

        try:
            from apps.task_monitor.application.operational_alerts import (
                record_operational_alert,
            )

            alert_id = record_operational_alert(
                level=text_fields["level"],
                task_name=text_fields["task_name"],
                title=text_fields["title"],
                message=text_fields["message"],
                metadata=dict(metadata) if metadata is not None else None,
                task_id=task_id,
            )
        except Exception:
            failure_count += 1
            logger.exception("Unexpected broker alert forwarding failure")
            continue
        if alert_id:
            alert_ids.append(alert_id)
        else:
            failure_count += 1
    return alert_ids, failure_count
