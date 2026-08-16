"""Configure the daily personal readiness evidence periodic task."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django_celery_beat.models import (
    CrontabSchedule,
    PeriodicTask,
    PeriodicTasks,
)

TASK_NAME = "personal-readiness-daily-evidence"
TASK_PATH = "apps.operational_readiness.application.tasks.run_personal_readiness_daily_task"
DEFAULT_RUN_HOUR = 16
DEFAULT_RUN_MINUTE = 10
DEFAULT_TASK_KWARGS: dict[str, object] = {
    "calendar_source": "auto",
    "run_workspace_refresh": True,
    "include_weekly_advisor": True,
    "persist_risk_report": True,
    "repair_accounts": False,
    "allow_unclosed_target_date": False,
    "trigger_source": "scheduler",
}


class Command(BaseCommand):
    help = "Create/update the personal readiness daily evidence periodic task."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--hour", type=int, default=DEFAULT_RUN_HOUR, help="Run hour (0-23).")
        parser.add_argument(
            "--minute",
            type=int,
            default=DEFAULT_RUN_MINUTE,
            help="Run minute (0-59).",
        )
        parser.add_argument(
            "--day-of-week",
            default="mon-fri",
            help="Celery beat day_of_week value. Default: mon-fri.",
        )
        parser.add_argument("--user-id", type=int, default=None, help="Optional user scope.")
        parser.add_argument(
            "--account-id",
            type=int,
            default=None,
            help="Optional account scope.",
        )
        parser.add_argument(
            "--calendar-source",
            choices=("auto", "qlib", "weekday"),
            default="auto",
            help="Trading calendar source for window validation.",
        )
        parser.add_argument(
            "--repair-accounts",
            action="store_true",
            help="Allow scheduled run to create missing readiness simulated accounts.",
        )
        parser.add_argument("--disable", action="store_true", help="Disable the periodic task.")

    def handle(self, *args: Any, **options: Any) -> None:
        hour = int(options["hour"])
        minute = int(options["minute"])
        day_of_week = str(options["day_of_week"] or "").strip()
        enabled = not bool(options["disable"])

        if hour < 0 or hour > 23:
            self.stderr.write(self.style.ERROR("--hour must be between 0 and 23"))
            return
        if minute < 0 or minute > 59:
            self.stderr.write(self.style.ERROR("--minute must be between 0 and 59"))
            return
        if not day_of_week:
            self.stderr.write(self.style.ERROR("--day-of-week cannot be empty"))
            return

        kwargs = _build_task_kwargs(
            user_id=options.get("user_id"),
            account_id=options.get("account_id"),
            calendar_source=str(options["calendar_source"]),
            repair_accounts=bool(options["repair_accounts"]),
        )

        with transaction.atomic():
            crontab = _get_crontab(hour=hour, minute=minute, day_of_week=day_of_week)
            PeriodicTask.objects.update_or_create(
                name=TASK_NAME,
                defaults=_build_periodic_task_defaults(
                    enabled=enabled,
                    kwargs=kwargs,
                    crontab=crontab,
                ),
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Personal readiness daily task configured"))
        self.stdout.write(f"  - {TASK_NAME}: {status} {day_of_week} {hour:02d}:{minute:02d}")


def _build_task_kwargs(
    *,
    user_id: int | None,
    account_id: int | None,
    calendar_source: str,
    repair_accounts: bool,
) -> dict[str, object]:
    kwargs = dict(DEFAULT_TASK_KWARGS)
    kwargs["calendar_source"] = calendar_source
    kwargs["repair_accounts"] = repair_accounts
    if user_id is not None:
        kwargs["user_id"] = int(user_id)
    if account_id is not None:
        kwargs["account_id"] = int(account_id)
    return kwargs


def _build_periodic_task_defaults(
    *,
    enabled: bool,
    kwargs: dict[str, object],
    crontab: CrontabSchedule,
) -> dict[str, object]:
    defaults = {
        "task": TASK_PATH,
        "enabled": enabled,
        "args": json.dumps([], ensure_ascii=True),
        "kwargs": json.dumps(kwargs, ensure_ascii=True),
        "description": "Daily personal investment readiness evidence collection",
        "interval": None,
        "solar": None,
        "clocked": None,
        "crontab": crontab,
    }
    safe_optional_defaults = {
        "queue": None,
        "exchange": None,
        "routing_key": None,
        "priority": None,
        "headers": json.dumps({}, ensure_ascii=True),
        "one_off": False,
        "start_time": None,
        "expires": None,
        "expire_seconds": None,
    }
    field_names = {field.name for field in PeriodicTask._meta.fields}
    defaults.update(
        {
            field_name: value
            for field_name, value in safe_optional_defaults.items()
            if field_name in field_names
        }
    )
    return defaults


def _get_crontab(*, hour: int, minute: int, day_of_week: str) -> CrontabSchedule:
    crontab_kwargs = {
        "minute": str(minute),
        "hour": str(hour),
        "day_of_week": day_of_week,
        "day_of_month": "*",
        "month_of_year": "*",
    }
    if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
        crontab_kwargs["timezone"] = "Asia/Shanghai"
    return CrontabSchedule.objects.get_or_create(**crontab_kwargs)[0]
