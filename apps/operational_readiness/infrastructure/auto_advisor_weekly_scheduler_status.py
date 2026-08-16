"""Status helpers for the auto-advisor weekly report scheduler."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django_celery_beat.models import PeriodicTask

AUTO_ADVISOR_WEEKLY_TASK_NAME = "dashboard-auto-advisor-weekly-report"
AUTO_ADVISOR_WEEKLY_TASK_PATH = "dashboard.generate_auto_advisor_weekly_reports"
PERSONAL_READINESS_DAILY_TASK_NAME = "personal-readiness-daily-evidence"
EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK = "fri"
EXPECTED_AUTO_ADVISOR_WEEKLY_HOUR = 17
EXPECTED_AUTO_ADVISOR_WEEKLY_MINUTE = 30
MIN_AUTO_ADVISOR_WEEKLY_MINUTES = 16 * 60 + 1
DEFAULT_PERSONAL_READINESS_DAILY_MINUTES = 16 * 60 + 10
EXPECTED_SCHEDULE_TIMEZONE = "Asia/Shanghai"
EXPECTED_SCHEDULE_DAY_OF_MONTH = "*"
EXPECTED_SCHEDULE_MONTH_OF_YEAR = "*"


def collect_auto_advisor_weekly_scheduler_status() -> dict[str, Any]:
    try:
        task = PeriodicTask.objects.filter(name=AUTO_ADVISOR_WEEKLY_TASK_NAME).first()
    except Exception as exc:
        return {
            "status": "error",
            "error": "auto_advisor_scheduler_query_failed",
            "exception_type": type(exc).__name__,
        }

    if task is None:
        return {
            "status": "missing",
            "name": AUTO_ADVISOR_WEEKLY_TASK_NAME,
            "task": AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "enabled": False,
        }

    crontab = task.crontab
    schedule = (
        {
            "minute": crontab.minute,
            "hour": crontab.hour,
            "day_of_week": crontab.day_of_week,
            "day_of_month": crontab.day_of_month,
            "month_of_year": crontab.month_of_year,
            "timezone": str(getattr(crontab, "timezone", "") or ""),
        }
        if crontab is not None
        else None
    )
    parsed_kwargs = _parse_scheduler_kwargs(task.kwargs)
    parsed_args = _parse_scheduler_args(getattr(task, "args", None))
    parsed_headers = _parse_scheduler_headers(getattr(task, "headers", None))
    run_controls = _collect_scheduler_run_controls(task)
    delivery_controls = _collect_scheduler_delivery_controls(
        task,
        effective_headers=parsed_headers.get("headers", {}),
    )
    run_metadata = _collect_scheduler_run_metadata(task)
    safety = _build_auto_advisor_weekly_scheduler_safety(
        task_path=task.task,
        enabled=bool(task.enabled),
        kwargs_error=parsed_kwargs.get("error"),
        effective_kwargs=parsed_kwargs.get("kwargs", {}),
        args_error=parsed_args.get("error"),
        args=parsed_args.get("args", []),
        headers_error=parsed_headers.get("error"),
        schedule=schedule,
        run_controls=run_controls,
        delivery_controls=delivery_controls,
    )
    return {
        "status": "ok" if safety["status"] == "ok" else "warning",
        "name": task.name,
        "task": task.task,
        "enabled": bool(task.enabled),
        "args": getattr(task, "args", "[]"),
        "effective_args": parsed_args.get("args", []),
        "kwargs": task.kwargs,
        "effective_kwargs": parsed_kwargs.get("kwargs", {}),
        "run_controls": run_controls,
        "delivery_controls": delivery_controls,
        "run_metadata": run_metadata,
        "safety": safety,
        "schedule": schedule,
    }


def build_auto_advisor_weekly_due_status(
    *,
    target_date: date,
    now: datetime | None = None,
    schedule: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return whether weekly-report persistence should exist for one target date."""

    schedule_config = _resolve_auto_advisor_weekly_schedule_config(schedule=schedule)
    expected_weekday = _parse_expected_weekday(schedule_config["day_of_week"])
    timezone = ZoneInfo(schedule_config["timezone"])
    scheduled_for = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        schedule_config["hour"],
        schedule_config["minute"],
        tzinfo=timezone,
    )
    if expected_weekday is None:
        return {
            "due": True,
            "reason": "weekly_schedule_day_unparseable",
            "scheduled_for": scheduled_for.isoformat(),
        }
    if target_date.weekday() != expected_weekday:
        next_scheduled_for = _build_next_scheduled_for(
            target_date=target_date,
            expected_weekday=expected_weekday,
            timezone=timezone,
            hour=schedule_config["hour"],
            minute=schedule_config["minute"],
        )
        return {
            "due": False,
            "reason": "weekly_report_not_scheduled_for_target_date",
            "scheduled_for": None,
            "next_scheduled_for": next_scheduled_for.isoformat(),
        }
    current_time = now.astimezone(timezone) if now is not None else datetime.now(timezone)
    if current_time < scheduled_for:
        return {
            "due": False,
            "reason": "weekly_report_schedule_not_due_yet",
            "scheduled_for": scheduled_for.isoformat(),
        }
    return {
        "due": True,
        "reason": "weekly_report_schedule_due",
        "scheduled_for": scheduled_for.isoformat(),
    }


def _resolve_auto_advisor_weekly_schedule_config(
    *,
    schedule: dict[str, str] | None,
) -> dict[str, Any]:
    effective_schedule = schedule or _load_current_auto_advisor_weekly_schedule()
    day_of_week = str(
        (effective_schedule or {}).get("day_of_week") or EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK
    )
    timezone = str((effective_schedule or {}).get("timezone") or EXPECTED_SCHEDULE_TIMEZONE)
    hour = _parse_single_crontab_number(str((effective_schedule or {}).get("hour") or ""))
    minute = _parse_single_crontab_number(str((effective_schedule or {}).get("minute") or ""))
    return {
        "day_of_week": day_of_week,
        "timezone": timezone,
        "hour": hour if hour is not None else EXPECTED_AUTO_ADVISOR_WEEKLY_HOUR,
        "minute": minute if minute is not None else EXPECTED_AUTO_ADVISOR_WEEKLY_MINUTE,
    }


def _load_current_auto_advisor_weekly_schedule() -> dict[str, str] | None:
    try:
        task = PeriodicTask.objects.filter(name=AUTO_ADVISOR_WEEKLY_TASK_NAME).first()
    except Exception:
        return None
    crontab = getattr(task, "crontab", None) if task is not None else None
    if crontab is None:
        return None
    return {
        "minute": crontab.minute,
        "hour": crontab.hour,
        "day_of_week": crontab.day_of_week,
        "day_of_month": crontab.day_of_month,
        "month_of_year": crontab.month_of_year,
        "timezone": str(getattr(crontab, "timezone", "") or ""),
    }


def _parse_scheduler_kwargs(raw_kwargs: str | None) -> dict[str, Any]:
    if not raw_kwargs:
        return {"kwargs": {}, "error": None}
    try:
        payload = json.loads(raw_kwargs)
    except json.JSONDecodeError as exc:
        return {"kwargs": {}, "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, dict):
        return {"kwargs": {}, "error": "kwargs_json_must_be_object"}
    return {"kwargs": payload, "error": None}


def _parse_scheduler_args(raw_args: str | None) -> dict[str, Any]:
    if not raw_args:
        return {"args": [], "error": None}
    try:
        payload = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return {"args": [], "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, list):
        return {"args": [], "error": "args_json_must_be_array"}
    return {"args": payload, "error": None}


def _parse_scheduler_headers(raw_headers: str | None) -> dict[str, Any]:
    if not raw_headers:
        return {"headers": {}, "error": None}
    try:
        payload = json.loads(raw_headers)
    except json.JSONDecodeError as exc:
        return {"headers": {}, "error": f"invalid_json: {exc.msg}"}
    if not isinstance(payload, dict):
        return {"headers": {}, "error": "headers_json_must_be_object"}
    return {"headers": payload, "error": None}


def _build_auto_advisor_weekly_scheduler_safety(
    *,
    task_path: str,
    enabled: bool,
    kwargs_error: Any,
    effective_kwargs: dict[str, Any],
    schedule: dict[str, str] | None,
    args_error: Any = None,
    args: list[Any] | None = None,
    headers_error: Any = None,
    run_controls: dict[str, Any] | None = None,
    delivery_controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not enabled:
        issues.append(
            {
                "code": "auto_advisor_weekly_scheduler_disabled",
                "message": "Scheduled auto-advisor weekly report generation is disabled.",
            }
        )
    if task_path != AUTO_ADVISOR_WEEKLY_TASK_PATH:
        issues.append(
            {
                "code": "unexpected_auto_advisor_weekly_task_path",
                "message": f"Expected {AUTO_ADVISOR_WEEKLY_TASK_PATH}, got {task_path}",
            }
        )
    if kwargs_error:
        issues.append(
            {
                "code": "invalid_auto_advisor_weekly_scheduler_kwargs",
                "message": str(kwargs_error),
            }
        )
    if args_error:
        issues.append(
            {
                "code": "invalid_auto_advisor_weekly_scheduler_args",
                "message": str(args_error),
            }
        )
    if args:
        issues.append(
            {
                "code": "unexpected_auto_advisor_weekly_scheduler_args",
                "message": "Weekly auto-advisor scheduler must not use positional args.",
            }
        )
    if headers_error:
        issues.append(
            {
                "code": "invalid_auto_advisor_weekly_scheduler_headers",
                "message": str(headers_error),
            }
        )
    issues.extend(_build_auto_advisor_weekly_kwargs_safety_issues(effective_kwargs))
    issues.extend(_build_run_control_safety_issues(run_controls=run_controls or {}))
    issues.extend(_build_delivery_control_safety_issues(delivery_controls=delivery_controls or {}))
    schedule_issue = _build_auto_advisor_weekly_schedule_safety_issue(schedule=schedule)
    if schedule_issue:
        issues.append(schedule_issue)
    return {
        "status": "warning" if issues else "ok",
        "enabled": enabled,
        "scope": _resolve_auto_advisor_weekly_scope(effective_kwargs),
        "issues": issues,
    }


def _build_auto_advisor_weekly_kwargs_safety_issues(
    effective_kwargs: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    allowed_keys = {"user_id", "account_ids"}
    for key in sorted(set(effective_kwargs) - allowed_keys):
        issues.append(
            {
                "code": "unexpected_auto_advisor_weekly_scheduler_kwarg",
                "message": f"Unexpected weekly auto-advisor scheduler kwarg: {key}.",
            }
        )
    user_id = effective_kwargs.get("user_id")
    if user_id is not None and (not isinstance(user_id, int) or user_id <= 0):
        issues.append(
            {
                "code": "invalid_auto_advisor_weekly_user_id",
                "message": "Weekly auto-advisor scheduler user_id must be a positive integer.",
            }
        )
    account_ids = effective_kwargs.get("account_ids")
    if account_ids is not None:
        if not isinstance(account_ids, list) or not account_ids:
            issues.append(
                {
                    "code": "invalid_auto_advisor_weekly_account_ids",
                    "message": "Weekly auto-advisor scheduler account_ids must be a non-empty list.",
                }
            )
        elif any(not isinstance(value, int) or value <= 0 for value in account_ids):
            issues.append(
                {
                    "code": "invalid_auto_advisor_weekly_account_ids",
                    "message": "Weekly auto-advisor scheduler account_ids must be positive integers.",
                }
            )
    if account_ids is not None and user_id is None:
        issues.append(
            {
                "code": "auto_advisor_weekly_account_ids_without_user",
                "message": "Weekly auto-advisor scheduler account_ids require user_id.",
            }
        )
    return issues


def _resolve_auto_advisor_weekly_scope(effective_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": effective_kwargs.get("user_id"),
        "account_ids": effective_kwargs.get("account_ids"),
        "all_active_accounts": not effective_kwargs.get("user_id"),
    }


def _build_auto_advisor_weekly_schedule_safety_issue(
    *,
    schedule: dict[str, str] | None,
) -> dict[str, str] | None:
    if schedule is None:
        return {
            "code": "missing_auto_advisor_weekly_crontab",
            "message": "Scheduled weekly auto-advisor report has no crontab schedule.",
        }
    timezone = str(schedule.get("timezone") or "")
    if timezone != EXPECTED_SCHEDULE_TIMEZONE:
        return {
            "code": "unexpected_auto_advisor_weekly_timezone",
            "message": (
                "Scheduled weekly auto-advisor report should use "
                f"{EXPECTED_SCHEDULE_TIMEZONE}, got {timezone or 'missing'}."
            ),
        }
    day_of_week = str(schedule.get("day_of_week") or "")
    if day_of_week != EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK:
        return {
            "code": "unexpected_auto_advisor_weekly_day_of_week",
            "message": (
                "Scheduled weekly auto-advisor report should run on "
                f"{EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK}, got {day_of_week or 'missing'}."
            ),
        }
    day_of_month = str(schedule.get("day_of_month") or "")
    if day_of_month != EXPECTED_SCHEDULE_DAY_OF_MONTH:
        return {
            "code": "unexpected_auto_advisor_weekly_day_of_month",
            "message": (
                "Scheduled weekly auto-advisor report should run every day-of-month, "
                f"got {day_of_month or 'missing'}."
            ),
        }
    month_of_year = str(schedule.get("month_of_year") or "")
    if month_of_year != EXPECTED_SCHEDULE_MONTH_OF_YEAR:
        return {
            "code": "unexpected_auto_advisor_weekly_month_of_year",
            "message": (
                "Scheduled weekly auto-advisor report should run every month, "
                f"got {month_of_year or 'missing'}."
            ),
        }
    hour = _parse_single_crontab_number(str(schedule.get("hour") or ""))
    minute = _parse_single_crontab_number(str(schedule.get("minute") or ""))
    if hour is None or minute is None:
        return {
            "code": "invalid_auto_advisor_weekly_time",
            "message": "Scheduled weekly auto-advisor report time must be a single hour/minute.",
        }
    daily_evidence_minutes = _resolve_daily_evidence_minutes()
    weekly_minutes = hour * 60 + minute
    if weekly_minutes < MIN_AUTO_ADVISOR_WEEKLY_MINUTES:
        return {
            "code": "unsafe_auto_advisor_weekly_time",
            "message": (
                "Scheduled weekly auto-advisor report should run after 16:00 "
                f"Asia/Shanghai, got {hour:02d}:{minute:02d}."
            ),
        }
    if weekly_minutes <= daily_evidence_minutes:
        return {
            "code": "auto_advisor_weekly_not_after_daily_evidence",
            "message": (
                "Scheduled weekly auto-advisor report should run after "
                "personal readiness daily evidence "
                f"({_format_minutes(daily_evidence_minutes)}), "
                f"got {hour:02d}:{minute:02d}."
            ),
        }
    return None


def _collect_scheduler_run_controls(task: Any) -> dict[str, Any]:
    return {
        "one_off": bool(getattr(task, "one_off", False)),
        "start_time": _optional_isoformat(getattr(task, "start_time", None)),
        "expires": _optional_isoformat(getattr(task, "expires", None)),
        "expire_seconds": getattr(task, "expire_seconds", None),
    }


def _optional_isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _resolve_daily_evidence_minutes() -> int:
    try:
        task = PeriodicTask.objects.filter(name=PERSONAL_READINESS_DAILY_TASK_NAME).first()
    except Exception:
        return DEFAULT_PERSONAL_READINESS_DAILY_MINUTES
    crontab = getattr(task, "crontab", None) if task is not None else None
    hour = _parse_single_crontab_number(str(getattr(crontab, "hour", "") or ""))
    minute = _parse_single_crontab_number(str(getattr(crontab, "minute", "") or ""))
    if hour is None or minute is None:
        return DEFAULT_PERSONAL_READINESS_DAILY_MINUTES
    return hour * 60 + minute


def _format_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _collect_scheduler_delivery_controls(
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


def _collect_scheduler_run_metadata(task: Any) -> dict[str, Any]:
    return {
        "last_run_at": _optional_isoformat(getattr(task, "last_run_at", None)),
        "total_run_count": getattr(task, "total_run_count", None),
        "date_changed": _optional_isoformat(getattr(task, "date_changed", None)),
    }


def _build_delivery_control_safety_issues(
    *,
    delivery_controls: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for field, code in [
        ("queue", "unexpected_auto_advisor_weekly_scheduler_queue"),
        ("exchange", "unexpected_auto_advisor_weekly_scheduler_exchange"),
        ("routing_key", "unexpected_auto_advisor_weekly_scheduler_routing_key"),
        ("priority", "unexpected_auto_advisor_weekly_scheduler_priority"),
    ]:
        value = delivery_controls.get(field)
        if value not in (None, ""):
            issues.append(
                {
                    "code": code,
                    "message": (
                        "Weekly auto-advisor scheduler should use default Celery "
                        f"delivery controls; {field} is {value}."
                    ),
                }
            )
    if delivery_controls.get("effective_headers"):
        issues.append(
            {
                "code": "unexpected_auto_advisor_weekly_scheduler_headers",
                "message": "Weekly auto-advisor scheduler should not set custom headers.",
            }
        )
    return issues


def _build_run_control_safety_issues(*, run_controls: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if run_controls.get("one_off") is True:
        issues.append(
            {
                "code": "auto_advisor_weekly_scheduler_one_off_enabled",
                "message": "Weekly auto-advisor scheduler must not be configured as one-off.",
            }
        )
    if run_controls.get("expires"):
        issues.append(
            {
                "code": "auto_advisor_weekly_scheduler_expires_enabled",
                "message": "Weekly auto-advisor scheduler must not have an expiration datetime.",
            }
        )
    if run_controls.get("expire_seconds") not in (None, ""):
        issues.append(
            {
                "code": "auto_advisor_weekly_scheduler_expire_seconds_enabled",
                "message": "Weekly auto-advisor scheduler must not expire after a fixed interval.",
            }
        )
    return issues


def _parse_single_crontab_number(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_expected_weekday(value: str) -> int | None:
    normalized = value.strip().lower()
    names = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
    if normalized in names:
        return names[normalized]
    try:
        parsed = int(normalized)
    except ValueError:
        return None
    if 0 <= parsed <= 6:
        return parsed
    return None


def _build_next_scheduled_for(
    *,
    target_date: date,
    expected_weekday: int,
    timezone: ZoneInfo,
    hour: int,
    minute: int,
) -> datetime:
    days_until = (expected_weekday - target_date.weekday()) % 7
    if days_until == 0:
        days_until = 7
    next_date = target_date + timedelta(days=days_until)
    return datetime(
        next_date.year,
        next_date.month,
        next_date.day,
        hour,
        minute,
        tzinfo=timezone,
    )
