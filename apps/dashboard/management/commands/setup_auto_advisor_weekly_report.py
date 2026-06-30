"""Configure personal auto-advisor weekly report generation."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks


class Command(BaseCommand):
    help = "Create/update the weekly auto-advisor report periodic task."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=17, help="Report hour (0-23)")
        parser.add_argument("--minute", type=int, default=30, help="Report minute (0-59)")
        parser.add_argument(
            "--day-of-week",
            default="fri",
            help="Celery beat day_of_week value, for example fri or 5",
        )
        parser.add_argument("--user-id", type=int, default=None, help="Optional user id")
        parser.add_argument(
            "--account-ids",
            default="",
            help="Optional comma-separated account ids used with --user-id",
        )
        parser.add_argument("--disable", action="store_true", help="Disable the periodic task")

    def handle(self, *args, **options):
        hour = int(options["hour"])
        minute = int(options["minute"])
        day_of_week = str(options["day_of_week"] or "fri").strip()
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
            account_ids_text=str(options.get("account_ids") or ""),
        )

        with transaction.atomic():
            crontab = _get_crontab(hour=hour, minute=minute, day_of_week=day_of_week)
            PeriodicTask.objects.update_or_create(
                name="dashboard-auto-advisor-weekly-report",
                defaults={
                    "task": "dashboard.generate_auto_advisor_weekly_reports",
                    "enabled": enabled,
                    "kwargs": json.dumps(kwargs, ensure_ascii=True),
                    "description": "Weekly personal auto-advisor report generation",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": crontab,
                },
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        scope = f"user_id={kwargs['user_id']}" if "user_id" in kwargs else "all active accounts"
        self.stdout.write(self.style.SUCCESS("Auto-advisor weekly report task configured"))
        self.stdout.write(
            f"  - dashboard-auto-advisor-weekly-report: {status} {day_of_week} "
            f"{hour:02d}:{minute:02d} ({scope})"
        )


def _build_task_kwargs(*, user_id: int | None, account_ids_text: str) -> dict:
    kwargs: dict[str, object] = {}
    if user_id is not None:
        kwargs["user_id"] = int(user_id)
    account_ids = [
        int(value.strip())
        for value in account_ids_text.split(",")
        if value.strip()
    ]
    if account_ids:
        kwargs["account_ids"] = account_ids
    return kwargs


def _get_crontab(*, hour: int, minute: int, day_of_week: str):
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
