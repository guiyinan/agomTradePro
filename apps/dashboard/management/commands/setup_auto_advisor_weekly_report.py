"""Configure the personal auto-advisor weekly report schedule safely."""

from __future__ import annotations

import importlib
import json
from typing import Any, cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

TASK_NAME = "dashboard-auto-advisor-weekly-report"
TASK_PATH = "dashboard.generate_auto_advisor_weekly_reports"
PERSONAL_READINESS_DAILY_TASK_NAME = "personal-readiness-daily-evidence"
DEFAULT_PERSONAL_READINESS_DAILY_MINUTES = 16 * 60 + 10

_beat_models = importlib.import_module("django_celery_beat.models")
CrontabSchedule: Any = _beat_models.CrontabSchedule
PeriodicTask: Any = _beat_models.PeriodicTask
PeriodicTasks: Any = _beat_models.PeriodicTasks

TaskKwargs = dict[str, object]


def _required_int(options: dict[str, object], key: str) -> int:
    value = options.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"--{key.replace('_', '-')} must be an integer")
    return value


def _required_bool(options: dict[str, object], key: str) -> bool:
    value = options.get(key)
    if not isinstance(value, bool):
        raise CommandError(f"--{key.replace('_', '-')} must be a boolean")
    return value


def _optional_positive_id(value: object, *, option_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CommandError(f"{option_name} must be a positive integer")
    return value


class Command(BaseCommand):
    """Create or update the weekly report task without broadening scope implicitly."""

    help = "Create/update the weekly auto-advisor report periodic task."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--hour", type=int, default=17)
        parser.add_argument("--minute", type=int, default=30)
        parser.add_argument("--day-of-week", default="fri")
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--account-ids", default="")
        parser.add_argument("--clear-scope", action="store_true")
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        del args
        hour = _required_int(options, "hour")
        minute = _required_int(options, "minute")
        if not 0 <= hour <= 23:
            raise CommandError("--hour must be between 0 and 23")
        if not 0 <= minute <= 59:
            raise CommandError("--minute must be between 0 and 59")
        day_value = options.get("day_of_week")
        if not isinstance(day_value, str) or not day_value.strip():
            raise CommandError("--day-of-week must be a non-empty string")
        day_of_week = day_value.strip()
        enabled = not _required_bool(options, "disable")
        clear_scope = _required_bool(options, "clear_scope")
        user_id = _optional_positive_id(options.get("user_id"), option_name="--user-id")
        account_ids_value = options.get("account_ids", "")
        if not isinstance(account_ids_value, str):
            raise CommandError("--account-ids must be a comma-separated string")
        if clear_scope and (user_id is not None or account_ids_value.strip()):
            raise CommandError("--clear-scope cannot be combined with user/account scope")

        daily_evidence_minutes = _resolve_daily_evidence_minutes()
        if hour * 60 + minute <= daily_evidence_minutes:
            raise CommandError(
                "Weekly auto-advisor report time must be later than "
                "personal readiness daily evidence time "
                f"({_format_minutes(daily_evidence_minutes)})."
            )
        timezone_value: object = getattr(settings, "TIME_ZONE", None)
        if not isinstance(timezone_value, str) or not timezone_value.strip():
            raise CommandError("TIME_ZONE must be a non-empty string")

        with transaction.atomic():
            existing_task = PeriodicTask.objects.select_for_update().filter(name=TASK_NAME).first()
            task_kwargs = _resolve_task_kwargs(
                existing_task=existing_task,
                user_id=user_id,
                account_ids_text=account_ids_value,
                clear_scope=clear_scope,
            )
            crontab = _get_crontab(
                hour=hour,
                minute=minute,
                day_of_week=day_of_week,
                timezone_name=timezone_value.strip(),
            )
            PeriodicTask.objects.update_or_create(
                name=TASK_NAME,
                defaults={
                    "task": TASK_PATH,
                    "enabled": enabled,
                    "kwargs": json.dumps(task_kwargs, ensure_ascii=True, allow_nan=False),
                    "description": "Weekly personal auto-advisor report generation",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": crontab,
                },
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Auto-advisor weekly report task configured"))
        self.stdout.write(
            f"  - {TASK_NAME}: {status} {day_of_week} "
            f"{hour:02d}:{minute:02d} ({_describe_scope(task_kwargs)})"
        )


def _resolve_task_kwargs(
    *,
    existing_task: object | None,
    user_id: int | None,
    account_ids_text: str,
    clear_scope: bool,
) -> TaskKwargs:
    """Resolve explicit scope, explicit clearing, or a valid existing scope."""

    if clear_scope:
        return {}
    if user_id is not None or account_ids_text.strip():
        return _build_task_kwargs(user_id=user_id, account_ids_text=account_ids_text)
    return _load_existing_task_kwargs(existing_task)


def _build_task_kwargs(*, user_id: int | None, account_ids_text: str) -> TaskKwargs:
    """Build a normalized, positive, deduplicated user/account scope."""

    try:
        parsed_ids = [int(value.strip()) for value in account_ids_text.split(",") if value.strip()]
    except ValueError as exc:
        raise CommandError("--account-ids must be comma-separated integers") from exc
    if any(account_id <= 0 for account_id in parsed_ids):
        raise CommandError("--account-ids must contain positive integers")
    account_ids = list(dict.fromkeys(parsed_ids))
    if account_ids and user_id is None:
        raise CommandError("--account-ids requires --user-id")
    result: TaskKwargs = {}
    if user_id is not None:
        result["user_id"] = user_id
    if account_ids:
        result["account_ids"] = account_ids
    return result


def _load_existing_task_kwargs(existing_task: object | None) -> TaskKwargs:
    """Load and validate existing scope without silently broadening it."""

    if existing_task is None:
        return {}
    raw_kwargs: object = getattr(existing_task, "kwargs", None)
    if not isinstance(raw_kwargs, str):
        raise CommandError("existing weekly task kwargs must be a JSON string")
    try:
        payload: object = json.loads(raw_kwargs or "{}")
    except json.JSONDecodeError as exc:
        raise CommandError("existing weekly task kwargs contain invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CommandError("existing weekly task kwargs must be a JSON object")
    if set(payload).difference({"user_id", "account_ids"}):
        raise CommandError("existing weekly task kwargs contain unsupported keys")
    user_id = _optional_positive_id(payload.get("user_id"), option_name="existing user_id")
    account_ids_value = payload.get("account_ids", [])
    if not isinstance(account_ids_value, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in account_ids_value
    ):
        raise CommandError("existing account_ids must be a positive integer list")
    if account_ids_value and user_id is None:
        raise CommandError("existing account_ids require user_id")
    result: TaskKwargs = {}
    if user_id is not None:
        result["user_id"] = user_id
    if account_ids_value:
        result["account_ids"] = list(dict.fromkeys(account_ids_value))
    return result


def _describe_scope(task_kwargs: TaskKwargs) -> str:
    user_id = task_kwargs.get("user_id")
    if not isinstance(user_id, int):
        return "all active accounts"
    account_ids = task_kwargs.get("account_ids")
    if isinstance(account_ids, list) and account_ids:
        return f"user_id={user_id}, account_ids={account_ids}"
    return f"user_id={user_id}"


def _resolve_daily_evidence_minutes() -> int:
    """Return the configured daily evidence time or the documented default when absent."""

    try:
        task = PeriodicTask.objects.filter(name=PERSONAL_READINESS_DAILY_TASK_NAME).first()
    except Exception as exc:
        raise CommandError(f"cannot read daily evidence schedule: {type(exc).__name__}") from exc
    crontab = getattr(task, "crontab", None) if task is not None else None
    hour = _parse_single_crontab_number(getattr(crontab, "hour", None), maximum=23)
    minute = _parse_single_crontab_number(getattr(crontab, "minute", None), maximum=59)
    if hour is None or minute is None:
        return DEFAULT_PERSONAL_READINESS_DAILY_MINUTES
    return hour * 60 + minute


def _parse_single_crontab_number(value: object, *, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= maximum else None


def _format_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _get_crontab(
    *,
    hour: int,
    minute: int,
    day_of_week: str,
    timezone_name: str,
) -> object:
    crontab_kwargs: dict[str, object] = {
        "minute": str(minute),
        "hour": str(hour),
        "day_of_week": day_of_week,
        "day_of_month": "*",
        "month_of_year": "*",
    }
    if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
        crontab_kwargs["timezone"] = timezone_name
    return cast(object, CrontabSchedule.objects.get_or_create(**crontab_kwargs)[0])
