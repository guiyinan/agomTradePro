"""Status helpers for the pre-readiness decision quote refresh scheduler."""

from __future__ import annotations

from typing import Any

from django_celery_beat.models import PeriodicTask

from apps.operational_readiness.infrastructure import scheduler_status_utils

QUOTE_PRE_READINESS_TASK_NAME = "decision-quote-pre-readiness-refresh"
QUOTE_PRE_READINESS_TASK_PATH = (
    "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task"
)
EXPECTED_QUOTE_PRE_READINESS_DAY_OF_WEEK = "1,2,3,4,5"
MIN_QUOTE_PRE_READINESS_POST_CLOSE_MINUTES = 15 * 60 + 1
EXPECTED_QUOTE_MAX_AGE_HOURS = 4.0
EXPECTED_SCHEDULE_TIMEZONE = "Asia/Shanghai"
EXPECTED_SCHEDULE_DAY_OF_MONTH = "*"
EXPECTED_SCHEDULE_MONTH_OF_YEAR = "*"


def collect_quote_pre_readiness_scheduler_status() -> dict[str, Any]:
    try:
        task = PeriodicTask.objects.filter(name=QUOTE_PRE_READINESS_TASK_NAME).first()
    except Exception as exc:
        return {
            "status": "error",
            "error": "quote_pre_readiness_scheduler_query_failed",
            "exception_type": type(exc).__name__,
        }

    if task is None:
        return {
            "status": "missing",
            "name": QUOTE_PRE_READINESS_TASK_NAME,
            "task": QUOTE_PRE_READINESS_TASK_PATH,
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
    parsed_kwargs = scheduler_status_utils.parse_scheduler_kwargs(task.kwargs)
    parsed_args = scheduler_status_utils.parse_scheduler_args(getattr(task, "args", None))
    parsed_headers = scheduler_status_utils.parse_scheduler_headers(getattr(task, "headers", None))
    run_controls = scheduler_status_utils.collect_scheduler_run_controls(task)
    delivery_controls = scheduler_status_utils.collect_scheduler_delivery_controls(
        task,
        effective_headers=parsed_headers.get("headers", {}),
    )
    run_metadata = scheduler_status_utils.collect_scheduler_run_metadata(task)
    safety = _build_quote_pre_readiness_scheduler_safety(
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


def _build_quote_pre_readiness_scheduler_safety(
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
                "code": "quote_pre_readiness_scheduler_disabled",
                "message": "Pre-readiness decision quote refresh is disabled.",
            }
        )
    if task_path != QUOTE_PRE_READINESS_TASK_PATH:
        issues.append(
            {
                "code": "unexpected_quote_pre_readiness_task_path",
                "message": f"Expected {QUOTE_PRE_READINESS_TASK_PATH}, got {task_path}.",
            }
        )
    if kwargs_error:
        issues.append(
            {
                "code": "invalid_quote_pre_readiness_scheduler_kwargs",
                "message": str(kwargs_error),
            }
        )
    if args_error:
        issues.append(
            {
                "code": "invalid_quote_pre_readiness_scheduler_args",
                "message": str(args_error),
            }
        )
    if args:
        issues.append(
            {
                "code": "unexpected_quote_pre_readiness_scheduler_args",
                "message": "Pre-readiness quote refresh scheduler must not use positional args.",
            }
        )
    if headers_error:
        issues.append(
            {
                "code": "invalid_quote_pre_readiness_scheduler_headers",
                "message": str(headers_error),
            }
        )
    issues.extend(_build_quote_pre_readiness_kwargs_safety_issues(effective_kwargs))
    issues.extend(
        _prefix_scheduler_issues(
            scheduler_status_utils.build_run_control_safety_issues(run_controls=run_controls or {})
        )
    )
    issues.extend(
        _prefix_scheduler_issues(
            scheduler_status_utils.build_delivery_control_safety_issues(
                delivery_controls=delivery_controls or {}
            )
        )
    )
    schedule_issue = _build_quote_pre_readiness_schedule_safety_issue(schedule=schedule)
    if schedule_issue:
        issues.append(schedule_issue)
    return {
        "status": "warning" if issues else "ok",
        "enabled": enabled,
        "asset_codes": effective_kwargs.get("asset_codes"),
        "quote_max_age_hours": effective_kwargs.get("quote_max_age_hours"),
        "issues": issues,
    }


def _build_quote_pre_readiness_kwargs_safety_issues(
    effective_kwargs: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    allowed_keys = {"asset_codes", "quote_max_age_hours"}
    for key in sorted(set(effective_kwargs) - allowed_keys):
        issues.append(
            {
                "code": "unexpected_quote_pre_readiness_scheduler_kwarg",
                "message": f"Unexpected pre-readiness quote scheduler kwarg: {key}.",
            }
        )
    quote_max_age_hours = effective_kwargs.get("quote_max_age_hours")
    if not isinstance(quote_max_age_hours, int | float) or quote_max_age_hours <= 0:
        issues.append(
            {
                "code": "invalid_quote_pre_readiness_max_age",
                "message": "quote_max_age_hours must be a positive number.",
            }
        )
    elif float(quote_max_age_hours) > EXPECTED_QUOTE_MAX_AGE_HOURS:
        issues.append(
            {
                "code": "quote_pre_readiness_max_age_too_loose",
                "message": (
                    "Pre-readiness quote refresh should preserve the decision quote freshness "
                    f"budget of {EXPECTED_QUOTE_MAX_AGE_HOURS} hours."
                ),
            }
        )
    asset_codes = effective_kwargs.get("asset_codes")
    if asset_codes is not None:
        if not isinstance(asset_codes, list) or not asset_codes:
            issues.append(
                {
                    "code": "invalid_quote_pre_readiness_asset_codes",
                    "message": "asset_codes must be a non-empty list when provided.",
                }
            )
        elif any(not isinstance(value, str) or not value.strip() for value in asset_codes):
            issues.append(
                {
                    "code": "invalid_quote_pre_readiness_asset_codes",
                    "message": "asset_codes entries must be non-empty strings.",
                }
            )
    return issues


def _build_quote_pre_readiness_schedule_safety_issue(
    *,
    schedule: dict[str, str] | None,
) -> dict[str, str] | None:
    if schedule is None:
        return {
            "code": "missing_quote_pre_readiness_crontab",
            "message": "Pre-readiness quote refresh has no crontab schedule.",
        }
    timezone = str(schedule.get("timezone") or "")
    if timezone != EXPECTED_SCHEDULE_TIMEZONE:
        return {
            "code": "unexpected_quote_pre_readiness_timezone",
            "message": (
                "Pre-readiness quote refresh should use "
                f"{EXPECTED_SCHEDULE_TIMEZONE}, got {timezone or 'missing'}."
            ),
        }
    day_of_week = str(schedule.get("day_of_week") or "")
    if day_of_week != EXPECTED_QUOTE_PRE_READINESS_DAY_OF_WEEK:
        return {
            "code": "unexpected_quote_pre_readiness_day_of_week",
            "message": (
                "Pre-readiness quote refresh should run on trading weekdays, "
                f"got {day_of_week or 'missing'}."
            ),
        }
    day_of_month = str(schedule.get("day_of_month") or "")
    if day_of_month != EXPECTED_SCHEDULE_DAY_OF_MONTH:
        return {
            "code": "unexpected_quote_pre_readiness_day_of_month",
            "message": "Pre-readiness quote refresh should run every day-of-month.",
        }
    month_of_year = str(schedule.get("month_of_year") or "")
    if month_of_year != EXPECTED_SCHEDULE_MONTH_OF_YEAR:
        return {
            "code": "unexpected_quote_pre_readiness_month_of_year",
            "message": "Pre-readiness quote refresh should run every month.",
        }
    hour = scheduler_status_utils.parse_single_crontab_number(str(schedule.get("hour") or ""))
    minute = scheduler_status_utils.parse_single_crontab_number(str(schedule.get("minute") or ""))
    if hour is None or minute is None:
        return {
            "code": "invalid_quote_pre_readiness_time",
            "message": "Pre-readiness quote refresh should use a concrete HH:MM crontab time.",
        }
    scheduled_minutes = hour * 60 + minute
    if scheduled_minutes < MIN_QUOTE_PRE_READINESS_POST_CLOSE_MINUTES:
        return {
            "code": "quote_pre_readiness_before_post_close",
            "message": ("Pre-readiness quote refresh should run after the 15:00 market close."),
        }
    return None


def _prefix_scheduler_issues(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "code": f"quote_pre_readiness_{item.get('code', 'scheduler_issue')}",
            "message": str(item.get("message") or ""),
        }
        for item in issues
    ]
