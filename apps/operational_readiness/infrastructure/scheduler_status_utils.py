"""Shared helpers for database-backed scheduler status checks."""

from __future__ import annotations

import json
from typing import Any


def parse_scheduler_kwargs(raw_kwargs: str | None) -> dict[str, Any]:
    if not raw_kwargs:
        return {"kwargs": {}, "error": None}
    try:
        payload = json.loads(raw_kwargs)
    except json.JSONDecodeError as exc:
        return {"kwargs": {}, "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, dict):
        return {"kwargs": {}, "error": "kwargs_json_must_be_object"}
    return {"kwargs": payload, "error": None}


def parse_scheduler_args(raw_args: str | None) -> dict[str, Any]:
    if not raw_args:
        return {"args": [], "error": None}
    try:
        payload = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return {"args": [], "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, list):
        return {"args": [], "error": "args_json_must_be_array"}
    return {"args": payload, "error": None}


def parse_scheduler_headers(raw_headers: str | None) -> dict[str, Any]:
    if not raw_headers:
        return {"headers": {}, "error": None}
    try:
        payload = json.loads(raw_headers)
    except json.JSONDecodeError as exc:
        return {"headers": {}, "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, dict):
        return {"headers": {}, "error": "headers_json_must_be_object"}
    return {"headers": payload, "error": None}


def collect_scheduler_run_controls(task: Any) -> dict[str, Any]:
    return {
        "one_off": bool(getattr(task, "one_off", False)),
        "start_time": optional_isoformat(getattr(task, "start_time", None)),
        "expires": optional_isoformat(getattr(task, "expires", None)),
        "expire_seconds": getattr(task, "expire_seconds", None),
    }


def optional_isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def collect_scheduler_delivery_controls(
    task: Any,
    *,
    effective_headers: dict[str, Any],
) -> dict[str, Any]:
    return {
        "queue": getattr(task, "queue", None),
        "exchange": getattr(task, "exchange", None),
        "routing_key": getattr(task, "routing_key", None),
        "priority": getattr(task, "priority", None),
        "headers": getattr(task, "headers", "{}"),
        "effective_headers": effective_headers,
    }


def collect_scheduler_run_metadata(task: Any) -> dict[str, Any]:
    return {
        "last_run_at": optional_isoformat(getattr(task, "last_run_at", None)),
        "total_run_count": getattr(task, "total_run_count", None),
        "date_changed": optional_isoformat(getattr(task, "date_changed", None)),
    }


def build_delivery_control_safety_issues(
    *,
    delivery_controls: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for field, code in [
        ("queue", "unexpected_scheduler_queue"),
        ("exchange", "unexpected_scheduler_exchange"),
        ("routing_key", "unexpected_scheduler_routing_key"),
        ("priority", "unexpected_scheduler_priority"),
    ]:
        value = delivery_controls.get(field)
        if value not in (None, ""):
            issues.append(
                {
                    "code": code,
                    "message": (
                        "Scheduled readiness evidence should use default Celery "
                        f"delivery controls; {field} is {value}."
                    ),
                }
            )
    if delivery_controls.get("effective_headers"):
        issues.append(
            {
                "code": "unexpected_scheduler_headers",
                "message": "Scheduled readiness evidence should not set custom headers.",
            }
        )
    return issues


def build_run_control_safety_issues(*, run_controls: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if run_controls.get("one_off") is True:
        issues.append(
            {
                "code": "scheduler_one_off_enabled",
                "message": "Scheduled readiness evidence must not be configured as one-off.",
            }
        )
    if run_controls.get("expires"):
        issues.append(
            {
                "code": "scheduler_expires_enabled",
                "message": "Scheduled readiness evidence must not have an expiration datetime.",
            }
        )
    if run_controls.get("expire_seconds") not in (None, ""):
        issues.append(
            {
                "code": "scheduler_expire_seconds_enabled",
                "message": "Scheduled readiness evidence must not expire after a fixed interval.",
            }
        )
    return issues


def parse_single_crontab_number(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed
